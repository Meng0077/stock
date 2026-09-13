"""D03 手动 Agent 的离线验收框架，不读取密钥，也不发送模型请求。

从项目根目录运行：
    PYTHONPATH=backend/src python backend/examples/verify_manual_agent.py

案例使用本地假响应，不会发送真实模型请求。
未实现的案例会显示为 PENDING，并让脚本以非零状态退出。
"""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

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

    def __init__(self, responses):
        self.responses = responses
        self.request_messages = []

    def create(self, **kwargs):
        # model_loop 调用的就是这个 create；kwargs 中包含本轮发给模型的 messages。**kwargs类似于js中...args
        self.request_messages.append(deepcopy(kwargs["messages"]))
        index = len(self.request_messages) - 1
        if index >= len(self.responses):
            raise AssertionError("模型请求次数超过预设响应数")
        return self.responses[index]


def tool_call(call_id, name, arguments):
    return CompletionMessageToolCall(
        id=call_id,
        type="function",
        function=Function(name=name, arguments=arguments),
    )


def tool_response(calls):
    message = CompletionMessage(role="assistant", tool_calls=calls)
    choice = SimpleNamespace(message=message, finish_reason="tool_calls")
    return SimpleNamespace(choices=[choice], usage=None)


def final_response(content, finish_reason="stop"):
    message = CompletionMessage(role="assistant", content=content)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def run_scenario(responses, max_rounds=agent.MAX_MODEL_ROUNDS, max_tools=agent.MAX_TOOL_CALLS):
    """用假模型响应运行一次 Agent，返回普通字典供测试检查。"""
    # 每个案例都要从初始对话开始；结束时还原全局变量。
    saved_messages = deepcopy(agent.messages)
    original_handlers = {}
    spies = {}
    for name in agent.TOOL_REGISTRY:
        original_handlers[name] = agent.TOOL_REGISTRY[name]["handler"]
        # Mock 会记录调用次数；wraps 保证原 handler 仍正常执行。
        spies[name] = Mock(wraps=original_handlers[name])
        # 记录次数的 Mock 替换原 handler；调用时仍会执行原 handler。但是会通过mock 记录调用次数
        agent.TOOL_REGISTRY[name]["handler"] = spies[name]

    completions = FakeCompletions(responses)
    # model_loop 需要 client.chat.completions.create 这个层级。 依赖注入， 用completions 替换 client.chat.completions， 使得调用create是调用FakeCompletions.create
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    stdout = StringIO()
    stderr = StringIO()
    status = None
    protocol_error_code = None
    events = []

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
                    events=events,
                )
            except agent.ToolCallProtocolError as error:
                protocol_error_code = error.code

        handler_calls = {}
        for name in spies:
            handler_calls[name] = spies[name].call_count

        # 返回副本：finally 会把全局 messages 和 handler 恢复原状。
        return {
            "status": status,
            "protocol_error_code": protocol_error_code,
            "model_requests": len(completions.request_messages),
            "handler_calls": handler_calls,
            "messages": deepcopy(agent.messages),
            "request_messages": completions.request_messages,
            "events": deepcopy(events),
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
        }
    finally:
        for name in original_handlers:
            agent.TOOL_REGISTRY[name]["handler"] = original_handlers[name]
        agent.messages[:] = saved_messages


def verify_basic_round_trip():
    """示例案例：验证「请求工具 → 按 ID 回传 → 得到最终回答」。

    第一条假响应要求查询 NVDA；第二条假响应模拟模型正常结束。
    这里检查的是工具往返协议，预设的最终正文不代表真实模型回答已验收。
    """
    result = run_scenario([
        tool_response([tool_call("call_quote", "get_quote", '{"company_id":"NVDA"}')]),
        final_response("NVDA 的教学模拟报价来自本地数据。"),
    ])

    # 两次模型请求中，只有第一次会启动 handler；第二次给出最终回答。
    assert result["status"] == 0
    assert result["model_requests"] == 2
    assert result["handler_calls"]["get_quote"] == 1
    assert result["handler_calls"]["get_company_profile"] == 0
    # request_messages[1] 是第二次请求时的对话；末尾应依次是 assistant 调用和 tool 结果。
    second_request = result["request_messages"][1]
    assert second_request[-2]["role"] == "assistant"
    assert second_request[-2]["tool_calls"][0]["id"] == "call_quote"
    assert second_request[-1]["tool_call_id"] == "call_quote"

    # tool 消息的 content 是 JSON 字符串，解析后检查成功标记和 fixture 来源。
    tool_messages = []
    for message in result["messages"]:
        if message["role"] == "tool":
            tool_messages.append(message)
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_quote"
    tool_result = json.loads(tool_messages[0]["content"])
    assert tool_result["ok"] is True
    assert tool_result["data"]["data_mode"] == "fixture"


def verify_multiple_tool_calls():
    # TODO：同一轮返回两个不同 ID；检查两条结果及第二次请求中的消息顺序。
    result = run_scenario([
        tool_response([
            tool_call("call_quote", "get_quote", '{"company_id":"NVDA"}'),
            #  get_company_profile + {"company_id": "NVDA"} -> 返回 fixture 公司资料。
            tool_call("call_company_profile", "get_company_profile", '{"company_id":"NVDA"}')
            ]),
        final_response("NVDA 的教学模拟报价来自本地数据。"),
    ])

    assert result["status"] == 0
    assert result["model_requests"] == 2
    assert result["handler_calls"]["get_quote"] == 1
    assert result["handler_calls"]["get_company_profile"] == 1

    second_request = result["request_messages"][1]
    assistant_message = second_request[-3]
    assert assistant_message["role"] == "assistant"
    assert len(assistant_message["tool_calls"]) == 2
    assert assistant_message["tool_calls"][0]["id"] == "call_quote"
    assert assistant_message["tool_calls"][0]["function"]["name"] == "get_quote"
    assert assistant_message["tool_calls"][1]["id"] == "call_company_profile"
    assert assistant_message["tool_calls"][1]["function"]["name"] == "get_company_profile"

    tools_message = [msg for msg in second_request if msg["role"] == "tool"]
    assert len(tools_message) == 2
    assert tools_message[0]["tool_call_id"] == "call_quote"
    assert tools_message[1]["tool_call_id"] == "call_company_profile"

    tool_result = [json.loads(msg["content"]) for msg in tools_message]
    assert tool_result[0]["ok"] is True
    assert tool_result[0]["data"]["data_mode"] == "fixture"
    assert "price" in tool_result[0]["data"]
    assert tool_result[1]["ok"] is True
    assert tool_result[1]["data"]["data_mode"] == "fixture"
    assert "company_name" in tool_result[1]["data"]

    # raise NotImplementedError


def verify_invalid_tool_requests():
    # TODO：错误 JSON、非字典、空字段、额外字段、未知工具；handler 次数应为 0。
    result = run_scenario([
        tool_response([
            # tool_call("call_quote_invalid", "get_quote_unknown", '["company_id": "", "aa": "ddddd"]'),
            tool_call("call_quote_invalid", "get_quote", '["company_id": "NVDA"]'),
            tool_call("call_quote_dict", "get_quote", '[]'),
            tool_call("call_quote_empty", "get_quote", '{"company_id": ""}'),
            tool_call("call_quote_extra", "get_quote", '{"company_id": "NVDA", "extra": "aaaa"}'),
            tool_call("call_quote_unknown_tool", "get_quote_unknown", '{"company_id": "NVDA"}'),
        ]),
        final_response("未取得报价。"),
    ])
    
    # assert result["status"] != 0
    assert result["status"] == 0
    assert result["model_requests"] == 2
    total = sum(result["handler_calls"].values())
    assert total == 0
    
    tool_result = {}
    total = 0
    for item in result["messages"]:
        if item["role"] == "tool":
            tool_result[item["tool_call_id"]] = json.loads(item["content"])
            total += 1
    assert total == 5
    
    expected_codes = {
        "call_quote_invalid": "invalid_json",
        "call_quote_dict": "invalid_arguments",
        "call_quote_empty": "invalid_arguments",
        "call_quote_extra": "invalid_arguments",
        "call_quote_unknown_tool": "unknown_tool",
    }
    for key, val in expected_codes.items():
        assert tool_result[key]["ok"] is False
        assert tool_result[key]["error"]["code"] == val
        

def verify_handler_failure():
    # TODO：AAPL 通过参数格式校验，但 handler 抛 ValueError；检查失败结果和次数。
    result = run_scenario([
        tool_response([
            tool_call("call_quote", "get_quote", '{"company_id":"AAPL"}'),
            ]),
        final_response("NVDA 的教学模拟报价来自本地数据。"),
    ])
    # print(json.dumps(result, ensure_ascii=False, indent=2))
    
    assert result["status"] == 0
    assert result["model_requests"] == 2
    assert result["handler_calls"]["get_quote"] == 1
    assert result["handler_calls"]["get_company_profile"] == 0
    
    tool_msg = result["messages"][-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_quote"
    content = json.loads(tool_msg["content"])
    assert content["ok"] is False
    assert content["error"]["code"] == "tool_rejected"
  
  
def verify_budgets():
    # TODO：五个合法工具调用最多执行四次；第三轮请求工具后不得发第四次请求。
    result = run_scenario([
        tool_response([
            tool_call("call_quote_a", "get_quote", '{"company_id":"NVDA"}'),
            tool_call("call_quote_b", "get_quote", '{"company_id":"NVDA"}'),
            ]),
        tool_response([
            tool_call("call_company_profile_a", "get_company_profile", '{"company_id":"NVDA"}'),
            ]),
        tool_response([
            tool_call("call_company_profile_b", "get_company_profile", '{"company_id":"NVDA"}'),
            ]),
        final_response("NVDA 的教学模拟报价来自本地数据。"),
    ])
    
    # print(json.dumps(result, ensure_ascii=False, indent=2))
    
    assert result["status"] != 0
    assert result["model_requests"] == 3
    assert result["handler_calls"]["get_quote"] == 2
    assert result["handler_calls"]["get_company_profile"] == 1
    
    result_b = run_scenario([
            tool_response([
                tool_call("call_quote_a", "get_quote", '{"company_id":"NVDA"}'),
                tool_call("call_quote_b", "get_quote", '{"company_id":"NVDA"}'),
                tool_call("call_company_profile_a", "get_company_profile", '{"company_id":"NVDA"}'),
                tool_call("call_company_profile_b", "get_company_profile", '{"company_id":"NVDA"}'),
                tool_call("call_company_profile_c", "get_company_profile", '{"company_id":"NVDA"}'),
                ]),
            final_response("NVDA 的教学模拟报价来自本地数据。"),
    ])
    
    # print(json.dumps(result_b, ensure_ascii=False, indent=2))
    
    assert result_b["status"] != 0
    assert result_b["model_requests"] == 1
    assert result_b["handler_calls"]["get_quote"] == 2
    assert result_b["handler_calls"]["get_company_profile"] == 2
    content = json.loads(result_b["messages"][-1]["content"])
    # print(json.dumps(content, ensure_ascii=False, indent=2))
    assert content['error']["code"] == "tool_call_budget_exhausted"

    tool_messages = [m for m in result_b["messages"] if m["role"] == "tool"]
    assert len(tool_messages) == 5
    assert tool_messages[-1]["tool_call_id"] == "call_company_profile_c"    
    # raise NotImplementedError

def verify_invalid_model_responses():
    # TODO：无 choices、空正文、截断、空 ID、重复 ID 都不能标记为 completed。
    no_choices = SimpleNamespace(choices=[], usage=None)
    response_no_choice = run_scenario([no_choices])
    
    assert response_no_choice["status"] == 1
    assert response_no_choice["model_requests"] == 1
    assert sum(response_no_choice["handler_calls"].values()) == 0
    
 
    response_no_content = run_scenario([
        final_response(""),
    ])
    
    assert response_no_content["status"] == 1
    assert response_no_content["model_requests"] == 1
    assert sum(response_no_content["handler_calls"].values()) == 0
    
    response_not_finish = run_scenario([
            final_response("未写完", finish_reason="length")
        ])
    assert response_not_finish["status"] == 1
    assert response_not_finish["model_requests"] == 1
    assert sum(response_not_finish["handler_calls"].values()) == 0
    
    
    response_no_id = run_scenario([
        tool_response([tool_call("", "get_quote", '{"company_id":"NVDA"}')]),
        final_response(""),
    ])
    # print(json.dumps(response_no_id, ensure_ascii=False, indent=2))
    
    assert response_no_id['protocol_error_code'] == 'missing_tool_call_id'
    assert sum(response_no_id['handler_calls'].values()) == 0
    assert response_no_id["model_requests"] == 1
    
    response_no_repeat = run_scenario([
            tool_response([
                tool_call("call_get_quote", "get_quote", '{"company_id":"NVDA"}'),
                tool_call("call_get_quote", "get_quote", '{"company_id":"NVDA"}'),
            ]),
        final_response(""),
    ])
    # print(json.dumps(response_no_repeat, ensure_ascii=False, indent=2))
    assert response_no_repeat["protocol_error_code"] == 'duplicate_tool_call_id'
    assert response_no_repeat["model_requests"] == 1
    assert sum(response_no_repeat['handler_calls'].values()) == 0
    

def verify_safe_logs_and_events():
    response = final_response(f"已完成。{FAKE_API_KEY}")
    response.usage = SimpleNamespace(prompt_tokens=5, completion_tokens=3, total_tokens=8)
    result = run_scenario([
        tool_response([tool_call("call_quote", "get_quote", '{"company_id":"NVDA"}')]),
        response,
    ])

    events = result["events"]
    assert result["status"] == 0
    assert [event["type"] for event in events] == [
        "model_request", "tool_requested", "tool_succeeded", "model_request", "run_finished"
    ]
    run_id = events[0]["run_id"]
    UUID(run_id)
    assert all(event["run_id"] == run_id for event in events)
    requests = [event for event in events if event["type"] == "model_request"]
    assert [event["round"] for event in requests] == [1, 2]
    assert all(isinstance(event["elapsed_ms"], (int, float)) and event["elapsed_ms"] >= 0 for event in requests)
    assert requests[0]["token_usage"] == "unavailable"
    assert requests[1]["token_usage"] == {
        "prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8
    }
    assert events[2]["tool_call_id"] == "call_quote"
    assert events[2]["company_id"] == "NVDA"
    assert events[2]["fixture_result"]["data_mode"] == "fixture"
    assert events[-1]["finally_status"] == "success"
    assert events[-1]["token"] == 8
    assert FAKE_API_KEY not in result["stdout"] + result["stderr"] + json.dumps(events)

    another_run = run_scenario([final_response("完成")])
    assert another_run["events"][0]["run_id"] != run_id

    unknown = run_scenario([
        tool_response([tool_call("call_unknown", f"unknown_{FAKE_API_KEY}", '{"company_id":"NVDA"}')]),
        final_response("工具不可用。"),
    ])
    unknown_events = unknown["events"]
    assert unknown_events[1]["tool"] == "unknown_tool"
    assert unknown_events[2]["tool"] == "unknown_tool"
    assert unknown_events[2]["code"] == "unknown_tool"
    assert FAKE_API_KEY not in unknown["stdout"] + unknown["stderr"] + json.dumps(unknown_events)


CASES = [
    ("基础工具往返", verify_basic_round_trip),
    ("多工具 ID 对应", verify_multiple_tool_calls),
    ("非法工具请求", verify_invalid_tool_requests),
    ("工具业务错误", verify_handler_failure),
    ("工具和轮数预算", verify_budgets),
    ("异常模型响应", verify_invalid_model_responses),
    ("安全日志与事件", verify_safe_logs_and_events),
]


def main():
    passed = 0
    failed = 0
    pending = 0
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
