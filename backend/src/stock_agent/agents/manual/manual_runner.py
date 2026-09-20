"""D06 Step 4：把 Week 1 Manual Agent 提炼成 API 可调用的运行入口。

现有 backend/examples/structured_agent.py 同时包含命令行、客户端生命周期、
事件和 model_loop。这里要提供应用层函数，让 CLI 与 API 最终都能复用同一条
Agent 路径，而不是从标准输出解析结果。

本文件只负责编排：
- 把 ResearchRequest 转成模型消息；
- 创建/复用 LLM 客户端并调用现有 model_loop；
- 从最终事件和 result_sink 构造 AgentRunResult；
- 把已知失败映射成现有 PublicError；
- 传播取消，并确保客户端被关闭。

不要复制工具 handler，不要绕过白名单，不要把原始异常放进返回值。
"""

import asyncio
import json
import math
import os
from pathlib import Path
from uuid import UUID

from stock_agent.agents.manual.manual_agent import model_loop
from stock_agent.agents.run_errors import error_code_from_exception
from stock_agent.api.schemas import AgentRunResult
from stock_agent.llm_client import LLMClient, get_llm_config
from stock_agent.schemas.errors import ErrorCode, PublicError, make_public_error
from stock_agent.schemas.research import ResearchRequest
from stock_agent.schemas.research_output import ResearchOutput

SYSTEM_PROMPT = """
你是一个只读的股票教学研究助手。

规则：
1. 查询公司资料或报价时，必须使用提供的白名单工具。
2. 尚未取得工具结果时，不得编造报价或公司事实。
3. 只能使用截至 as_of 已经可获得的资料。
4. data_mode 为 fixture 时，必须明确说明数据是本地教学模拟数据，
   不得描述为实时行情、真实报价或投资建议。
5. 必须区分事实、推断和缺失信息。
6. 最终只输出符合 ResearchOutput JSON Schema 的 JSON 对象。
7. 最终没有引用任何证据时，data_mode 必须为 null。
"""


def build_initial_messages(request: ResearchRequest) -> list[dict[str, object]]:
    """把已校验的研究请求转换为 Manual Agent 的初始消息。

    输入：
        request：包含 company_id、question、data_mode、带时区 as_of 的请求。

    输出：
        可传给 model_loop(initial_messages=...) 的消息列表；不得包含密钥。

    功能：
        明确告诉模型标的、用户问题、资料模式和截止时间；当 data_mode 为
        fixture 时，提示最终回答不得声称使用实时行情。
    """
    # D06-Step-4.1：组装 system/user 消息，内容由离线测试固定验证。
    return [
        {
            "role": "system",
            "content": (
                f"{SYSTEM_PROMPT}\n"
                "ResearchOutput JSON Schema：\n"
                f"{json.dumps(ResearchOutput.model_json_schema(), ensure_ascii=False)}"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "company_id": request.company_id,
                    "question": request.question,
                    "data_mode": request.data_mode,
                    "as_of": request.as_of.isoformat(),
                },
                ensure_ascii=False,
            ),
        },
    ]


BACKEND = Path(__file__).resolve().parents[4]
TASK_TIMEOUT_SECONDS = 300


def failed_run(run_id: UUID, code: ErrorCode) -> AgentRunResult:
    """输入运行 ID 和固定错误码；输出不含原始异常的安全失败结果。"""
    return AgentRunResult(
        run_id=run_id,
        status="cancelled" if code == "cancelled" else "failed",
        result=None,
        error=make_public_error(code),
    )


def result_from_agent_state(
    run_id: UUID,
    events: list[dict[str, object]],
    result_sink: dict[str, object],
) -> AgentRunResult:
    """把 model_loop 的终态事件和结果容器转换为安全结构化结果。

    输入：当前 run_id、运行事件和 result_sink。
    输出：成功时携带 ResearchOutput；失败时只携带固定 PublicError。
    功能：只读取属于当前 run_id 的最后一个 run_finished；任何缺失、矛盾或
    无法校验的内部数据都降级为 model_error，不向 API 暴露内部内容。
    """

    run_id_text = str(run_id)
    terminal = next(
        (
            event
            for event in reversed(events)
            if event.get("type") == "run_finished"
            and event.get("run_id") == run_id_text
        ),
        None,
    )
    if terminal is None:
        return failed_run(run_id, "model_error")

    status = terminal.get("status")
    if status in ("completed", "insufficient_information"):
        try:
            output = ResearchOutput.model_validate(result_sink["final_output"])
            return AgentRunResult(
                run_id=run_id,
                status=status,
                result=output,
                error=None,
            )
        except (KeyError, TypeError, ValueError):
            return failed_run(run_id, "model_error")

    if status in ("failed", "cancelled"):
        try:
            public_error = PublicError.model_validate(terminal["error"])
            return AgentRunResult(
                run_id=run_id,
                status=status,
                result=None,
                error=public_error,
            )
        except (KeyError, TypeError, ValueError):
            return failed_run(run_id, "model_error")

    return failed_run(run_id, "model_error")


async def run_manual_agent(
    request: ResearchRequest,
    run_id: UUID,
) -> AgentRunResult:
    """执行一次同步等待完成的 Manual Agent 运行。

    输入：
        request：已经通过 HTTP/Pydantic 校验的 ResearchRequest。
        run_id：由 API 层生成的本次运行 UUID；所有事件必须复用它。

    输出：
        AgentRunResult。正常结果携带 ResearchOutput；失败或取消只携带
        固定 PublicError，不携带原始异常。

    功能：
        复用现有 model_loop、预算、超时、工具注册表和证据校验，管理客户端
        生命周期，并把目前的退出码/事件/result_sink 汇总成结构化结果。

    异常约定：
        asyncio.CancelledError 必须继续向外传播；其余预期模型/网络错误转成
        安全终态。不得静默吞掉异常后继续使用未赋值的模型响应。
    """
    # D06-Step-4.2：加载配置；配置无效时返回安全 model_error。
    config = get_llm_config(BACKEND / ".env")
    if not config:
        return failed_run(run_id, "model_error")

    try:
        timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "300"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        return failed_run(run_id, "model_error")

    # D06-Step-4.3：创建 events/result_sink，调用 build_initial_messages。
    events: list[dict[str, object]] = []
    result_sink: dict[str, object] = {}
    messages = build_initial_messages(request)

    # D06-Step-4.4：在总超时内调用现有 model_loop，并传入同一 run_id。
    total_limit = None
    try:
        async with LLMClient(
            provider=config.provider,
            api_key=config.api_key,
            timeout=timeout,
        ) as client:
            async with asyncio.timeout(TASK_TIMEOUT_SECONDS) as total_limit:
                await model_loop(
                    client=client,
                    model=config.model,
                    model_timeout=timeout,
                    result_sink=result_sink,
                    run_id=str(run_id),
                    initial_messages=messages,
                    initial_evidence_ids=set(),
                    events=events,
                )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        code = error_code_from_exception(
            error,
            total_timeout_expired=(
                total_limit is not None and total_limit.expired()
            ),
        )
        return failed_run(run_id, code)

    # D06-Step-4.5～4.7：构造安全终态；上方上下文管理器负责关闭与取消清理。
    return result_from_agent_state(run_id, events, result_sink)
