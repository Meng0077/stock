"""D04 整合练习占位，按 docs/day04.md 实现。

Task 2：请求与解析结构化输出（详见 docs/day04/02_structured_output.md）。

离线解析样例已放在 backend/tests/test_research_output.py：合法 JSON、非法 JSON、
合法但缺字段，以及代码围栏包裹的文本。
TODO 2 文档和本地 SDK 已核对：结果与来源见 docs/day04/02_structured_output.md；
真实模型响应留待 TODO 7 验证。
TODO 3：按已核对的官方文档使用 response_format={"type": "json_object"}
构造请求，在提示中说明字段，并保留 ResearchOutput 的应用层校验。
TODO 4 已实现：--preview 展示输入与 schema；不读取或打印密钥，不调用 API。
TODO 5：检查响应是否无 choices、空正文、拒答或长度截断；这些情况都不能
作为完整研究结果，也不应靠随意修补文本通过解析。
TODO 6：完整正文先经过 Pydantic 校验，再检查证据 ID 和 data_mode；
工具调用与结构化输出若需分开请求，最终生成请求也计入模型轮数预算。
TODO 7：分别标记离线样例与真实模型结果，记录所用输出方式和验证结果。

后续任务 TODO：复用 D03 工具注册表与循环约束；格式修复最多一次；管理
异步客户端、单工具超时、总时限、取消与清理；使用安全错误对象和事件记录。
TODO：在 __main__ 下启动；导入本文件不得请求网络。

运行约定：PYTHONPATH=backend/src python backend/examples/structured_agent.py --preview
预览命令已实现；真实模型流程仍需完成后续验收。
"""


import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

from pydantic import ValidationError
from zai import ZhipuAiClient
from zai.core import APIStatusError, APITimeoutError
from dotenv import load_dotenv
import os
import uuid

from stock_agent.agents.tool_calling import (
    ToolCallProtocolError,
    build_tool_definitions,
    execute_tool_and_return,
)
from stock_agent.schemas.research_output import ResearchOutput



BACKEND = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT = "你是股票分析助手。仅依据用户提供的资料回答，区分事实、推断和缺失信息。"
MAX_MODEL_ROUNDS=3
MAX_TOOL_CALLS=4


messages = [
    {
        "role": "system",
        "content": f"""
            你是一个教学研究助手。
            查询公司资料或报价时，请使用提供的工具。
            工具返回的是本地模拟数据，不能描述为实时行情。
            尚未取得工具结果时，不要编造报价。
            请按照以下 JSON Schema 格式返回:
            {json.dumps(ResearchOutput.model_json_schema(), ensure_ascii=False)}
            """
    },
    {
        "role": "user",
        "content": f"""
            请查询 NVDA 的教学模拟报价和公司介绍。
            请按照以下 JSON Schema 格式返回:
            {json.dumps(ResearchOutput.model_json_schema(), ensure_ascii=False)}
        """,
    },
]

def model_loop(client, model, api_key, max_round = MAX_MODEL_ROUNDS, max_tool = MAX_TOOL_CALLS, events = None) -> int:
    if events is None:
        events = []
    run_messages = deepcopy(messages)
    round = 0
    tool_calls_executed = 0
    run_id = str(uuid.uuid4())

    while round < max_round:
        round += 1
        try:
            response = client.chat.completions.create(
                model=model,
                messages=run_messages,
                tools=build_tool_definitions(),
                response_format={
                    "type": "json_object"
                },
            )
        except Exception:
            raise
        # finally:

        if response.usage is not None:
            usage = {}
            for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = getattr(response.usage, field, None)
                usage[field] = value if value is not None else "unavailable"

        choices = response.choices
        if not choices:
            print("模型没有返回结果")
            return 1

        message = choices[0].message
        if message.tool_calls:
            if round >= max_round:
                print("模型请求了工具调用，但已达到最大轮数，结束循环。")
                return 1
            if tool_calls_executed >= max_tool:
                print("模型请求了工具调用，但已达到最大工具调用次数，结束循环。")
                return 1
            try:
                tool_calls_executed = execute_tool_and_return(
                    message,
                    messages=run_messages,
                    events=events,
                    run_id=run_id,
                    tool_calls_executed=tool_calls_executed,
                    max_tools=max_tool,
                )
            except ToolCallProtocolError as error:
                print(f"工具调用协议错误：{error}", file=sys.stderr)
                return 1
            if tool_calls_executed >= max_tool:
                print("模型请求了工具调用，但已达到最大工具调用次数，结束循环。")
                return 1
            continue
        elif choices[0].finish_reason != "stop" or not message.content or not  message.content.strip():
            print("未正常完成 或 响应错误：模型没有返回工具调用或可用正文")
            return 1
        else:
            content = message.content
            try:
                result = ResearchOutput.model_validate_json(content)
            except ValidationError:
                print("模型输出不符合 ResearchOutput", file=sys.stderr)
                return 1
            return 0
    return 1



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D04 结构化研究 Agent 练习")
    parser.add_argument("--preview", action="store_true", help="离线展示模型输入、工具声明和输出 schema")
    args = parser.parse_args(argv)

    if args.preview:
        print(json.dumps({
            "messages": messages,
            "tools": build_tool_definitions(),
            "response_format": {"type": "json_object"},
            "research_output_schema": ResearchOutput.model_json_schema(),
        }, ensure_ascii=False, indent=2))
        return 0

    load_dotenv(BACKEND / ".env", override=False)
    api_key = os.getenv("ZHIPU_API_KEY", "").strip()
    model = os.getenv("MODEL_NAME", "").strip()
    if not api_key or not model:
        print("配置错误：请设置 ZHIPU_API_KEY 和 MODEL_NAME。", file=sys.stderr)
        return 1
    try:
        timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "30"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        print("配置错误：MODEL_TIMEOUT_SECONDS 必须是大于 0 的有限数字。", file=sys.stderr)
        return 1

    client = None
    status = 1
    try:
        client = ZhipuAiClient(api_key=api_key, timeout=timeout, max_retries=0)
        status = model_loop(client, model, api_key)
    except APITimeoutError:
        print("模型请求超时。", file=sys.stderr)
    except APIStatusError:
        print("模型服务返回错误状态。", file=sys.stderr)
    except Exception:
        print("模型调用失败；原始异常已隐藏。", file=sys.stderr)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                print("模型客户端关闭失败。", file=sys.stderr)
                status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
