"""D04 Task 4：格式修复的离线请求次数与失败边界。"""

import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from zai.types.chat.chat_completion import CompletionMessage, CompletionMessageToolCall, Function


VALID_OUTPUT = (
    '{"status":"insufficient_information","facts":[],"inferences":[],'
    '"missing_information":["缺少资料"],"data_mode":"fixture"}'
)
MISSING_FIELD_OUTPUT = (
    '{"status":"insufficient_information","facts":[],"inferences":[],'
    '"missing_information":["PRIVATE_MARKER"]}'
)
INVALID_EVIDENCE_OUTPUT = (
    '{"status":"completed","facts":[{"text":"报价为 100 元","evidence_ids":["E99"]}],'
    '"inferences":[],"missing_information":[],"data_mode":"fixture"}'
)


def load_agent():
    module_path = Path(__file__).parents[1] / "examples" / "structured_agent.py"
    spec = importlib.util.spec_from_file_location("structured_agent_repair", module_path)
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    return agent


def response(content=None, *, tool_calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=CompletionMessage(role="assistant", content=content, tool_calls=tool_calls),
            finish_reason="tool_calls" if tool_calls else "stop",
        )],
        usage=None,
    )


def fake_client(*responses):
    requests = []

    async def create(**kwargs):
        requests.append(deepcopy(kwargs["messages"]))
        return responses[len(requests) - 1]

    client = SimpleNamespace(create=create)
    return client, requests


def test_valid_first_answer_needs_no_repair():
    client, requests = fake_client(response(VALID_OUTPUT))
    events = []

    assert asyncio.run(load_agent().model_loop(client, "offline", "fake-key", events=events)) == 0
    assert len(requests) == 1
    assert events[0]["status"] == "insufficient_information"
    assert "error" not in events[0]


def test_structure_error_gets_one_repair_with_safe_error_details():
    client, requests = fake_client(response(MISSING_FIELD_OUTPUT), response(VALID_OUTPUT))

    assert asyncio.run(load_agent().model_loop(client, "offline", "fake-key")) == 0
    assert len(requests) == 2
    repair_prompt = json.loads(requests[1][-1]["content"])
    assert repair_prompt["original_answer"] == MISSING_FIELD_OUTPUT
    assert "data_mode" in repair_prompt["schema"]["properties"]
    assert any(error["loc"] == ["data_mode"] for error in repair_prompt["errors"])
    assert "PRIVATE_MARKER" not in json.dumps(repair_prompt["errors"])
    assert all(
        "input" not in error and "ctx" not in error and "url" not in error
        for error in repair_prompt["errors"]
    )


def test_second_structure_error_stops_without_third_request():
    client, requests = fake_client(response(MISSING_FIELD_OUTPUT), response(MISSING_FIELD_OUTPUT))
    events = []

    assert asyncio.run(load_agent().model_loop(client, "offline", "fake-key", events=events)) == 1
    assert len(requests) == 2
    assert events[0]["error"]["code"] == "invalid_output"
    assert "PRIVATE_MARKER" not in json.dumps(events)


def test_exhausted_model_budget_prevents_repair_request():
    client, requests = fake_client(response(MISSING_FIELD_OUTPUT))
    events = []

    assert asyncio.run(load_agent().model_loop(
        client, "offline", "fake-key", max_round=1, events=events
    )) == 1
    assert len(requests) == 1
    assert events[0]["error"]["code"] == "budget_exhausted"


def test_invalid_evidence_does_not_trigger_format_repair():
    client, requests = fake_client(response(INVALID_EVIDENCE_OUTPUT))
    events = []

    assert asyncio.run(load_agent().model_loop(client, "offline", "fake-key", events=events)) == 1
    assert len(requests) == 1
    assert events[0]["error"]["code"] == "invalid_evidence"


def test_second_invalid_json_records_syntax_error_without_third_request():
    client, requests = fake_client(response("```json\n{}\n```"), response("not-json"))
    events = []

    assert asyncio.run(load_agent().model_loop(client, "offline", "fake-key", events=events)) == 1
    assert len(requests) == 2
    assert events[0]["error"]["code"] == "invalid_json"


def test_data_mode_mismatch_is_distinct_from_unknown_evidence():
    live_output = VALID_OUTPUT.replace('"fixture"', '"live"')
    client, requests = fake_client(response(live_output))
    events = []

    assert asyncio.run(load_agent().model_loop(client, "offline", "fake-key", events=events)) == 1
    assert len(requests) == 1
    assert events[0]["error"]["code"] == "data_mode_mismatch"


def test_repair_answer_cannot_request_tools():
    tool_call = CompletionMessageToolCall(
        id="unexpected-tool",
        type="function",
        function=Function(name="get_quote", arguments='{"company_id":"NVDA"}'),
    )
    client, requests = fake_client(response(MISSING_FIELD_OUTPUT), response(tool_calls=[tool_call]))
    events = []

    assert asyncio.run(load_agent().model_loop(client, "offline", "fake-key", events=events)) == 1
    assert len(requests) == 2
    assert len(events) == 1
    assert events[0]["type"] == "run_finished"
    assert events[0]["error"]["code"] == "invalid_tool_call"
