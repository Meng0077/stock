"""手写 Agent 共用的工具声明、协议检查和工具结果回传。"""

import asyncio
import json
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import ValidationError
from stock_agent.llm_client import (
    LLMMessage,
    LLMToolCall,
)

from stock_agent.tools.registry import TOOL_REGISTRY, execute_tool

TOOL_TIMEOUT_SECONDS = 15


def build_tool_definitions() -> list[dict[str, Any]]:
    """根据白名单和参数模型生成只读工具声明。"""
    descriptions = {
        "get_quote": "只读工具；当前仅支持 NVDA，返回本地 fixture 教学模拟报价，不是真实行情。",
        "get_company_profile": "只读工具；当前仅支持 NVDA，返回本地 fixture 公司名称和业务简介。",
        "retrieve_knowledge": "只读工具；检索本地公司教学文档并返回证据片段，无可用资料时返回空列表。",
    }
    tool_definitions = []
    for name, info in TOOL_REGISTRY.items():
        tool_definitions.append({
            "type": "function",
            "function": {
                "name": name,
                "description": descriptions[name],
                "parameters": info["params_model"].model_json_schema(),
            },
        })
    return tool_definitions


class ToolCallProtocolError(ValueError):
    """工具调用协议错误；只保存固定错误码和安全提示。"""

    _MESSAGES = {
        "missing_tool_call_id": "工具调用 ID 不能为空",
        "duplicate_tool_call_id": "同一条消息中存在重复的工具调用 ID",
    }

    def __init__(self, code: Literal["missing_tool_call_id", "duplicate_tool_call_id"]):
        self.code = code
        super().__init__(self._MESSAGES[code])


def validate_tool_call_ids(
    tool_calls: Sequence[LLMToolCall],
) -> None:
    """在执行任何工具前，检查本轮所有调用 ID。"""
    ids_seen = set()
    for call in tool_calls:
        if not isinstance(call.id, str) or not call.id.strip():
            raise ToolCallProtocolError("missing_tool_call_id")
        if call.id in ids_seen:
            raise ToolCallProtocolError("duplicate_tool_call_id")
        ids_seen.add(call.id)


async def execute_tool_and_return(
    message: LLMMessage,
    *,
    messages: list[dict[str, Any]],
    events: list[dict[str, Any]],
    run_id: str,
    tool_calls_executed: int,
    max_tools: int,
    allowed_ids: set[str] | None = None,
) -> int:
    """执行本轮工具调用，将 assistant/tool 消息和安全事件写入本次运行状态。"""
    tool_calls = message.tool_calls or []
    validate_tool_call_ids(tool_calls)
    messages.append(message.model_dump(exclude_none=True, include={"role", "content", "tool_calls"}))

    def count_execution() -> None:
        nonlocal tool_calls_executed
        tool_calls_executed += 1

    for idx, call in enumerate(tool_calls):
        event_tool_name = call.function.name if call.function.name in TOOL_REGISTRY else "unknown_tool"
        events.append({
            "type": "tool_requested",
            "run_id": run_id,
            "tool_call_id": call.id,
            "tool": event_tool_name,
        })
        try:
            args = json.loads(call.function.arguments)
        except json.JSONDecodeError:
            response = {"ok": False, "error": {"code": "invalid_json", "message": "工具参数不是有效的 JSON。"}}
        else:
            if not isinstance(args, dict):
                response = {"ok": False, "error": {"code": "invalid_arguments", "message": "工具参数必须是 JSON 对象。"}}
            elif call.function.name not in TOOL_REGISTRY:
                response = {"ok": False, "error": {"code": "unknown_tool", "message": "请求的工具不在白名单中。"}}
            elif tool_calls_executed >= max_tools:
                response = {
                    "ok": False,
                    "error": {
                        "code": "tool_call_budget_exhausted",
                        "message": f"工具调用次数已达上限 {max_tools}，无法执行第 {idx + 1} 次调用。",
                    },
                }
            else:
                try:
                    async with asyncio.timeout(TOOL_TIMEOUT_SECONDS) as tool_limit:
                        result = await execute_tool(call.function.name, args, before_execute=count_execution)
                except TimeoutError:
                    if not tool_limit.expired():
                        raise
                    response = {
                        "ok": False,
                        "error": {"code": "tool_timeout", "message": "工具调用超时。"},
                    }
                except ValidationError:
                    response = {"ok": False, "error": {"code": "invalid_arguments", "message": "工具参数不符合要求。"}}
                except ValueError:
                    response = {"ok": False, "error": {"code": "tool_rejected", "message": "该工具目前只支持 NVDA 的本地教学数据。"}}
                else:
                    response = {"ok": True, "data": result}

        evidence_id = None
        if response["ok"] and allowed_ids is not None:
            evidence_id = f"E{len(allowed_ids) + 1}"
            response["evidence_id"] = evidence_id

        if response["ok"]:
            events.append({
                "type": "tool_succeeded",
                "run_id": run_id,
                "tool_call_id": call.id,
                "tool": event_tool_name,
                "company_id": response["data"]["company_id"],
                "fixture_result": response["data"],
                "evidence_id": evidence_id,
                "tool_calls_executed": tool_calls_executed,
            })
        else:
            events.append({
                "type": "tool_failed",
                "run_id": run_id,
                "tool_call_id": call.id,
                "tool": event_tool_name,
                "tool_calls_executed": tool_calls_executed,
                "code": response["error"]["code"],
            })

        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(response, ensure_ascii=False),
        })
        if evidence_id is not None and allowed_ids is not None:
            allowed_ids.add(evidence_id)

    return tool_calls_executed
