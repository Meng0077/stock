"""D06 Step 5：FastAPI 薄入口。

FastAPI 与 uvicorn 已在 Step 2 安装并锁定。本模块导入时只创建应用和注册
路由，不读取模型配置、不创建模型客户端，也不访问网络。

目标：POST /api/runs 只做请求校验、run_id 生成、依赖调用和公开响应映射。
路由中不要复制 model_loop、工具执行或证据校验。
"""

import asyncio
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI

from stock_agent.agents.manual.manual_runner import failed_run
from stock_agent.agents.run_errors import error_code_from_exception
from stock_agent.api.dependencies import AgentRunner, get_agent_runner
from stock_agent.api.schemas import RunResponse
from stock_agent.schemas.research import ResearchRequest


def new_run_id() -> UUID:
    """无输入；为每个 HTTP 请求生成新的 UUID；输出 UUID 对象。"""
    # D06-Step-5.2：uuid4 每次生成新值；连续调用由 Step 6 离线测试验证。
    return uuid4()


async def create_run(
    request: ResearchRequest,
    runner: Annotated[AgentRunner, Depends(get_agent_runner)],
) -> RunResponse:
    """执行 POST /api/runs 的应用逻辑。

    输入：
        request：FastAPI 已校验的 ResearchRequest。
        runner：通过 Depends(get_agent_runner) 注入的异步运行函数。

    输出：
        RunResponse，只包含 run_id、确定终态、ResearchOutput 或 PublicError。

    功能：
        生成 run_id，使用相同 ID 调用 runner，再把 AgentRunResult 映射成
        RunResponse。未知异常必须转换为安全错误，不能把异常正文返回客户端。
    """
    # D06-Step-5.3：生成 run_id，并把同一 UUID 传给 runner。
    run_id = new_run_id()
    try:
        agent_result = await runner(request=request, run_id=run_id)
        if agent_result.run_id != run_id:
            return RunResponse.from_agent_result(
                failed_run(run_id, "model_error")
            )

        # D06-Step-5.4：只把明确允许公开的字段映射到 RunResponse。
        return RunResponse.from_agent_result(agent_result)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        # D06-Step-5.5：未知异常只转换成固定错误，不返回异常正文。
        code = error_code_from_exception(
            error,
            total_timeout_expired=False,
        )
        return RunResponse.from_agent_result(failed_run(run_id, code))


def create_app() -> FastAPI:
    """无输入；创建并配置 FastAPI；输出可供测试和 uvicorn 使用的应用。"""
    # D06-Step-5.6～5.9：这里只组装应用、响应模型、路由和依赖声明。
    application = FastAPI()
    application.post(
        "/api/runs",
        response_model=RunResponse,
    )(create_run)
    return application


# D06-Step-5.10：模块导入只组装应用，不读取密钥、不创建客户端、不访问网络。
app = create_app()
