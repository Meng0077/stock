"""D03 手动 Agent 的离线验收框架，不读取密钥，也不发送模型请求。

从项目根目录运行：
    PYTHONPATH=backend/src python backend/examples/verify_manual_agent.py

目前只有基础工具往返案例已实现；待完成的案例会显示为 PENDING，
并让脚本以非零状态退出，避免误认为第 8 步已经验收通过。
"""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import dataclass
from io import StringIO
import json
from types import SimpleNamespace
from typing import Callable

from zai.types.chat.chat_completion import (
    CompletionMessage,
    CompletionMessageToolCall,
    Function,
)

import manual_agent as agent


INITIAL_MESSAGES = deepcopy(agent.messages)
FAKE_API_KEY = "FAKE_SECRET_MARKER"


class FakeCompletions:
    """依次返回预设响应，同时记录模型请求次数和收到的 messages。"""

    def __init__(self, responses: list[object]):
        self.responses = responses
        self.request_messages: list[list[dict]] = []

    def create(self, **kwargs):
        self.request_messages.append(deepcopy(kwargs["messages"]))
        index = len(self.request_messages) - 1
        if index >= len(self.responses):
            raise AssertionError("模型请求次数超过预设响应数")
        return self.responses[index]


def tool_call(call_id: str, name: str, arguments: str) -> CompletionMessageToolCall:
    return CompletionMessageToolCall(
        id=call_id,
        type="function",
        function=Function(name=name, arguments=arguments),
    )


def tool_response(*calls: CompletionMessageToolCall):
    message = CompletionMessage(role="assistant", tool_calls=list(calls))
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    return SimpleNamespace(choices=[choice], usage=None)


def final_response(content: str, finish_reason: str = "stop"):
    message = CompletionMessage(role="assistant", content=content)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


@dataclass
class RunSnapshot:
    status: int | None
    protocol_error_code: str | None
    model_requests: int
    handler_calls: list[tuple[str, str]]
    messages: list[dict]
    request_messages: list[list[dict]]
    stdout: str
    stderr: str


def run_scenario(
    responses: list[object],
    *,
    max_rounds: int = agent.MAX_MODEL_ROUNDS,
    max_tools: int = agent.MAX_TOOL_CALLS,
) -> RunSnapshot:
    """隔离一个案例，调用真实 Agent 循环，但用假客户端替代网络。"""
    saved_messages = deepcopy(agent.messages)
    saved_handlers = {
        name: entry["handler"] for name, entry in agent.TOOL_REGISTRY.items()
    }
    handler_calls: list[tuple[str, str]] = []

    for name, original_handler in saved_handlers.items():
        def spy(company_id: str, *, _name=name, _handler=original_handler):
            handler_calls.append((_name, company_id))
            return _handler(company_id)

        agent.TOOL_REGISTRY[name]["handler"] = spy

    completions = FakeCompletions(responses)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    stdout, stderr = StringIO(), StringIO()
    status = None
    protocol_error_code = None

    try:
        agent.messages[:] = deepcopy(INITIAL_MESSAGES)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                status = agent.model_loop(
                    fake_client,
                    model="offline-test",
                    api_key=FAKE_API_KEY,
                    max_rounds=max_rounds,
                    max_tools=max_tools,
                )
            except agent.ToolCallProtocolError as error:
                protocol_error_code = error.code

        # TODO：manual_agent 提供 events 参数后，在此传入并加入 RunSnapshot。
        return RunSnapshot(
            status=status,
            protocol_error_code=protocol_error_code,
            model_requests=len(completions.request_messages),
            handler_calls=handler_calls.copy(),
            messages=deepcopy(agent.messages),
            request_messages=completions.request_messages,
            stdout=stdout.getvalue(),
            stderr=stderr.getvalue(),
        )
    finally:
        for name, original_handler in saved_handlers.items():
            agent.TOOL_REGISTRY[name]["handler"] = original_handler
        agent.messages[:] = saved_messages


def verify_basic_round_trip() -> None:
    """示例案例：一次工具调用、按 ID 回传、随后得到最终回答。"""
    result = run_scenario([
        tool_response(tool_call("call_quote", "get_quote", '{"company_id":"NVDA"}')),
        final_response("NVDA 的教学模拟报价来自本地数据。"),
    ])

    assert result.status == 0
    assert result.model_requests == 2
    assert result.handler_calls == [("get_quote", "NVDA")]
    assert result.request_messages[1][-2]["role"] == "assistant"
    assert result.request_messages[1][-2]["tool_calls"][0]["id"] == "call_quote"
    assert result.request_messages[1][-1]["tool_call_id"] == "call_quote"

    tool_messages = [item for item in result.messages if item["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_quote"
    tool_result = json.loads(tool_messages[0]["content"])
    assert tool_result["ok"] is True
    assert tool_result["data"]["data_mode"] == "fixture"


def verify_multiple_tool_calls() -> None:
    # TODO：同一轮返回两个不同 ID；检查两条结果及第二次请求中的消息顺序。
    raise NotImplementedError


def verify_invalid_tool_requests() -> None:
    # TODO：错误 JSON、非字典、空字段、额外字段、未知工具；handler 次数应为 0。
    raise NotImplementedError


def verify_handler_failure() -> None:
    # TODO：AAPL 通过参数格式校验，但 handler 抛 ValueError；检查失败结果和次数。
    raise NotImplementedError


def verify_budgets() -> None:
    # TODO：五个合法工具调用最多执行四次；第三轮请求工具后不得发第四次请求。
    raise NotImplementedError


def verify_invalid_model_responses() -> None:
    # TODO：无 choices、空正文、截断、空 ID、重复 ID 都不能标记为 completed。
    raise NotImplementedError


def verify_safe_logs_and_events() -> None:
    # TODO：假敏感标记不能泄露；检查 run_id、事件类型、耗时、用量和终态。
    # 当前 manual_agent 尚未提供事件记录，完成该接口后再补这里的断言。
    raise NotImplementedError


CASES: tuple[tuple[str, Callable[[], None]], ...] = (
    ("基础工具往返", verify_basic_round_trip),
    ("多工具 ID 对应", verify_multiple_tool_calls),
    ("非法工具请求", verify_invalid_tool_requests),
    ("工具业务错误", verify_handler_failure),
    ("工具和轮数预算", verify_budgets),
    ("异常模型响应", verify_invalid_model_responses),
    ("安全日志与事件", verify_safe_logs_and_events),
)


def main() -> int:
    passed = failed = pending = 0
    for name, check in CASES:
        try:
            check()
        except NotImplementedError:
            pending += 1
            print(f"PENDING {name}")
        except Exception as error:
            failed += 1
            # 不打印异常原文，避免未来的测试数据或密钥被带入输出。
            print(f"FAIL    {name} ({type(error).__name__})")
        else:
            passed += 1
            print(f"PASS    {name}")

    print(f"汇总：通过 {passed}，失败 {failed}，待完成 {pending}")
    return 1 if failed else 2 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
