"""D03 手动工具调用入口：第 4 步已实现，后续步骤待完成。

按 docs/day03.md 的顺序完成第 4～7 步：
4. build_tool_definitions：构造工具声明。
    1. 定义 build_tool_definitions() -> list，声明 get_quote 和 get_company_profile。
    2. 每个工具声明包含 type="function"，以及 function 下的 name、description、parameters。
    3. parameters 使用 CompanyToolParams.model_json_schema() 生成，避免手写规则与本地校验不一致。
    4. 描述明确写出：只读工具、当前仅支持 NVDA、返回本地 fixture 数据；报价不是真实行情。
5. parse_arguments：解析并检查 JSON 参数。
    1. 从 response.choices[0].message 中读取 tool_calls；先检查 choices 是否为空。
    2. 没有工具调用时，检查是否存在正常结束的最终正文；空正文或截断不能当成成功。
    3. 有工具调用时遍历列表，读取每次调用的 id、function.name、function.arguments。
    4. function.arguments 通常是 JSON 字符串：使用 json.loads，不使用 eval。
    5. JSON 解析成功后，确认结果是 dict；合法 JSON 也可能是数组、数字或 null。
    6. 确认调用 ID 非空，同一条消息内 ID 不重复；否则停止本次流程并报告协议错误，不能猜 ID。
    7. 将工具名和参数字典交给 execute_tool，由注册表入口检查白名单和 Pydantic 参数规则。
6. 执行工具并按 tool_call_id 回传结果。
    1. 每轮收到工具调用时，先把该轮 assistant 消息（包含完整 tool_calls）加入 messages。
    2. 按顺序处理每个工具请求。调用第 3 步的 execute_tool，并保留 fixture/source/时间字段。
    3. 成功结果包装为 {"ok": true, "data": 工具返回值}。
    4. 可处理的错误包装为 {"ok": false, "error": {"code": 本地错误类别, "message": 安全说明}}。
    5. 用 json.dumps(..., ensure_ascii=False) 把结果转成字符串。
    6. 为每个工具调用追加一条消息：role="tool"、tool_call_id=该次调用的原始 ID、content=结果字符串。
    7. 全部工具调用都有对应结果后，再携带更新后的 messages 请求模型。
7. 编写有轮数和工具次数限制的模型循环。
定义 MAX_MODEL_ROUNDS=3、MAX_TOOL_CALLS=4。
    1. 一轮决策指一次模型 API 请求；最终生成回答也算一轮。
    2. 每次发请求前检查轮数，发起时计数；API 失败也算已尝试的一轮。关闭 SDK 自动重试，便于解释实际次数。
    3. 工具执行计数放在真正调用 handler 之前。被白名单或参数校验拒绝的不算执行；函数开始后抛出 ValueError 仍算一次执行尝试。
    4. 若当前 execute_tool 把校验和执行封装在一起，可调整入口以传入预算或拆出准备步骤；不能执行结束后才发现超限。
    5. 工具调用顺序执行；第 5 次工具执行必须被阻止。给未执行的调用生成预算耗尽错误结果。
    6. 预算耗尽后明确结束，不再发起新的模型请求。此前的部分结果可以记录，但不是完整研究结论。
    7. 第 3 轮若仍请求工具，本练习选择直接以轮数耗尽结束，不再执行无后续模型轮次可用的工具。
    8. 没有工具调用且正文正常结束才标记 completed；API 错误、协议错误和预算耗尽分别记录终态。
8. 添加脱敏事件记录，配合 verify_manual_agent.py 验证。
    1. 用事件列表或逐行 JSON 记录 model_request、tool_requested、tool_succeeded、tool_failed、run_finished。
    2. 记录轮数、工具调用 ID、白名单工具名、校验后的公司标识、fixture 结果、执行次数和终态。
    3. 每轮记录模型耗时及可获得的 token 用量；用量缺失写明 unavailable，不编造为 0。
    4. 每次运行分配 run_id。可使用 uuid.uuid4，方便区分多次运行。
    5. 不记录 API Key、请求头、原始异常、模型内部推理或未经筛选的参数对象。未知工具名可记录为固定的 unknown_tool。
    6. 保存演示记录到 docs/day03/ 下，标清 fixture、offline_simulation 或 real_api，不能把离线响应冒充真实模型。


建议把 main() 启动放在 if __name__ == "__main__": 下，
让验证脚本导入本文件时不会读取密钥或发送请求。
提供 --preview 只显示输入与工具声明。

运行方式（项目根目录、已激活虚拟环境）：
    PYTHONPATH=backend/src python backend/examples/manual_agent.py --preview
直接运行会请求模型；--preview 不读取密钥或访问网络。
"""
import math

from stock_agent.agents.preview import format_preview
from stock_agent.agents.tool_calling import (
    ToolCallProtocolError,
    build_tool_definitions,
    execute_tool_and_return,
)
from stock_agent.tools.registry import TOOL_REGISTRY
from pathlib import Path
from zai import ZhipuAiClient
from zai.core import APIStatusError, APITimeoutError
from dotenv import load_dotenv
import os
import sys
from hello_model  import explain_api_error
import argparse
import json
import time
import uuid


MAX_MODEL_ROUNDS=3
MAX_TOOL_CALLS=4
BACKEND = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT = "你是财报阅读助手。仅依据用户提供的资料回答，区分事实、推断和缺失信息。"
messages = [
    {
        "role": "system",
        "content": (
            "你是一个教学研究助手。"
            "查询公司资料或报价时，请使用提供的工具。"
            "工具返回的是本地模拟数据，不能描述为实时行情。"
            "尚未取得工具结果时，不要编造报价。"
        ),
    },
    {
        "role": "user",
        "content": "请查询 NVDA 的教学模拟报价和公司介绍。",
    },
]



# TODO：第 7 步，有限循环。
# TODO：第 8 步，事件记录及 main 入口。

def run_finished_events(events, round, tools, finally_status, token=None, run_id=None):
    events.append({
        "type": "run_finished",
        "run_id": run_id,
        "round": round,
        "tools": tools,
        "finally_status": finally_status,
        "token": token if token is not None else "unavailable"
    })


def model_loop(client: ZhipuAiClient, model: str, api_key: str, max_rounds: int = MAX_MODEL_ROUNDS, max_tools: int = MAX_TOOL_CALLS, events=None) :
    """模型循环，限制轮数和工具调用次数。"""
    if events is None:
        events = []
    run_id = str(uuid.uuid4())
    rounds = 0
    tool_calls_executed = 0
    
    response = None
    while rounds < max_rounds:
        rounds += 1
        curEvent = {
            "type": "model_request",
            "run_id": run_id,
            "round": rounds,
            "token_usage": "unavailable",
        }
        events.append(curEvent)
        request_started = time.perf_counter()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=build_tool_definitions(),
                thinking={"type": "disabled"},
                max_tokens=1200,
                # stream=False,
            )
        except Exception:
            run_finished_events(events, rounds, tool_calls_executed, "model_request_failed", run_id=run_id)
            raise
        finally:
            curEvent["elapsed_ms"] = round((time.perf_counter() - request_started) * 1000, 3)

        if response.usage is not None:
            usage = {}
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(response.usage, field, None)
                usage[field] = value if value is not None else "unavailable"
            curEvent["token_usage"] = usage
                
        if not response.choices:
            # 处理空响应
            # curEvent.reason = "response_no_choices"
            run_finished_events(events, rounds, tool_calls_executed, "response_no_choices", run_id=run_id)
            return 1
        choice = response.choices[0]
        message = choice.message
        if message.tool_calls:
            if rounds >= max_rounds:
                print("模型请求了工具调用，但已达到最大轮数，结束循环。")
                run_finished_events(events, rounds, tool_calls_executed, "over_max_rounds", run_id=run_id)
                return 1
            if tool_calls_executed >= max_tools:
                print("模型请求了工具调用，但已达到最大工具调用次数，结束循环。")
                run_finished_events(events, rounds, tool_calls_executed, "tool_calls_executed", run_id=run_id)
                return 1
            print("模型请求了工具调用：")
            try:
                tool_calls_executed = execute_tool_and_return(
                    message,
                    messages=messages,
                    events=events,
                    run_id=run_id,
                    tool_calls_executed=tool_calls_executed,
                    max_tools=max_tools,
                )
            except ToolCallProtocolError as error:
                run_finished_events(events, rounds, tool_calls_executed, error.code, run_id=run_id)
                raise
            if tool_calls_executed >= max_tools:
                print("工具调用次数已达上限，结束循环。")
                run_finished_events(events, rounds, tool_calls_executed, "tool_calls_executed", run_id=run_id)
                return 1
            continue
        elif message.content and message.content.strip():
            if choice.finish_reason != "stop":
                print("回答未正常结束，可能已达到输出上限，请勿当作完整分析。", file=sys.stderr)
                # curEvent.reason = "somehow"
                run_finished_events(events, rounds, tool_calls_executed, choice.finish_reason, run_id=run_id)
                return 1
            print(message.content.replace(api_key, "[REDACTED]"))
            print("\nToken 用量：")

            if response.usage is None:
                print("供应商未返回用量（不表示用量为零）。")
            else:
                for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    print(f"  {field}: {getattr(response.usage, field, None)}")
            run_finished_events(events, rounds, tool_calls_executed, "success", getattr(response.usage, "total_tokens", None), run_id)

            return 0
        else:
            print("响应错误：模型没有返回工具调用或可用正文。", file=sys.stderr)
            run_finished_events(events, rounds, tool_calls_executed, "no_content_or_tools", run_id=run_id)
            return 1
    run_finished_events(events, rounds, tool_calls_executed, "model_round_budget_exhausted", run_id=run_id)
    return 1

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="只显示模型输入，不发送请求")
    parser.add_argument("--question", help="本次要询问的内容；不传则使用示例问题")
    parser.add_argument("--record-events", type=Path, help="把本次真实调用的脱敏事件保存为 JSON")
    # parser.add_argument("--model", help="临时覆盖模型名称，可用于验证错误模型配置")
    args = parser.parse_args()
    if args.question is not None:
        messages[1]["content"] = args.question
    
    if args.preview:
        print("=== 模型输入 ===")
        print(format_preview(messages))
        print("\n=== 工具声明 ===")
        print(format_preview(build_tool_definitions()))
        return 0
    
    
    load_dotenv(BACKEND / ".env", override=False)
    api_key = os.getenv("ZHIPU_API_KEY", "").strip()
    model = os.getenv("MODEL_NAME", "").strip()
    try:
        timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "30"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        print("配置错误：MODEL_TIMEOUT_SECONDS 必须是大于 0 的有限数字。", file=sys.stderr)
        return 1
    
    if not api_key or not model:
        print("配置错误：请填写 backend/.env 中的 ZHIPU_API_KEY 和 MODEL_NAME。", file=sys.stderr)
        return 1
    client = None
    events = []
    status = 1
    try:
        # 2. 发送一次请求：关闭自动重试和深度思考，限制输出长度。
        client = ZhipuAiClient(api_key=api_key, timeout=timeout, max_retries=0)
        status = model_loop(client, model, api_key, events=events)
    except APITimeoutError:
        print("请求超时：请检查网络或增加超时配置；远端请求可能仍在执行。", file=sys.stderr)
    except APIStatusError as error:
        print(explain_api_error(error), file=sys.stderr)
    except ToolCallProtocolError as error:
        print(f"协议错误：{error}", file=sys.stderr)
    except Exception:
        print("调用失败：请检查网络和依赖版本；原始异常已隐藏以保护密钥。", file=sys.stderr)
    finally:
        if args.record_events is not None and events:
            try:
                args.record_events.write_text(
                    json.dumps({"source": "real_api", "events": events}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                print("事件记录保存失败；请检查输出路径。", file=sys.stderr)
                status = 1
        if client is not None:
            client.close()
    return status

if __name__ == "__main__":
    raise SystemExit(main())
    # 仅显示工具声明，避免误调用模型。
    # import json
    # print(json.dumps(build_tool_definitions(), indent=2, ensure_ascii=False))
