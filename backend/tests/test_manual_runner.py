"""D06 Manual Agent runner 的安全错误映射测试。"""

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from stock_agent.agents.manual import manual_runner
from stock_agent.agents.manual.manual_runner import (
    build_initial_messages,
    failed_run,
    result_from_agent_state,
)
from stock_agent.agents.manual.manual_agent import record_run_finished
from stock_agent.agents.run_errors import (
    error_code_from_exception,
    safe_message_from_exception,
)
from stock_agent.schemas.research import ResearchRequest


RUN_ID = UUID("12345678-1234-5678-1234-567812345678")


def make_request() -> ResearchRequest:
    return ResearchRequest(
        company_id="NVDA",
        question="查询教学模拟报价",
        data_mode="fixture",
        as_of="2026-09-15T16:00:00+08:00",
    )


def configure_runner(monkeypatch) -> list[bool]:
    monkeypatch.setattr(
        manual_runner,
        "get_llm_config",
        lambda path: SimpleNamespace(
            provider="deepseek",
            api_key="PRIVATE_API_KEY",
            model="offline",
        ),
    )
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "30")
    closed: list[bool] = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            closed.append(True)

    monkeypatch.setattr(manual_runner, "LLMClient", lambda **kwargs: FakeClient())
    return closed


def test_build_initial_messages_serializes_request_as_json():
    messages = build_initial_messages(make_request())

    assert [message["role"] for message in messages] == ["system", "user"]
    assert "ResearchOutput JSON Schema" in messages[0]["content"]
    assert json.loads(messages[1]["content"]) == {
        "company_id": "NVDA",
        "question": "查询教学模拟报价",
        "data_mode": "fixture",
        "as_of": "2026-09-15T16:00:00+08:00",
    }


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("model_error", "failed"),
        ("model_timeout", "failed"),
        ("total_timeout", "failed"),
        ("cancelled", "cancelled"),
    ],
)
def test_failed_run_builds_safe_structured_result(code, status):
    result = failed_run(RUN_ID, code)

    assert result.run_id == RUN_ID
    assert result.status == status
    assert result.result is None
    assert result.error.code == code


@pytest.mark.parametrize(
    ("error", "total_timeout_expired", "expected"),
    [
        (httpx.ReadTimeout("PRIVATE_DETAIL"), False, "model_timeout"),
        (TimeoutError("PRIVATE_DETAIL"), True, "total_timeout"),
        (TimeoutError("PRIVATE_DETAIL"), False, "model_error"),
        (ValueError("PRIVATE_DETAIL"), False, "model_error"),
        (RuntimeError("PRIVATE_DETAIL"), False, "model_error"),
    ],
)
def test_exception_mapping_returns_only_fixed_error_code(
    error,
    total_timeout_expired,
    expected,
):
    code = error_code_from_exception(
        error,
        total_timeout_expired=total_timeout_expired,
    )
    result = failed_run(RUN_ID, code)

    assert code == expected
    assert "PRIVATE_DETAIL" not in result.model_dump_json()


@pytest.mark.parametrize(
    ("error", "total_timeout_expired", "expected"),
    [
        (httpx.ReadTimeout("PRIVATE_DETAIL"), False, "模型请求超时。"),
        (TimeoutError("PRIVATE_DETAIL"), True, "任务总时限已到。"),
        (TimeoutError("PRIVATE_DETAIL"), False, "模型调用失败；原始异常已隐藏。"),
        (ValueError("PRIVATE_DETAIL"), False, "模型响应解析失败。"),
        (RuntimeError("PRIVATE_DETAIL"), False, "模型调用失败；原始异常已隐藏。"),
    ],
)
def test_exception_mapping_returns_safe_log_message(
    error,
    total_timeout_expired,
    expected,
):
    message = safe_message_from_exception(
        error,
        total_timeout_expired=total_timeout_expired,
    )

    assert message == expected
    assert "PRIVATE_DETAIL" not in message


def test_missing_config_returns_agent_run_result(monkeypatch):
    monkeypatch.setattr(manual_runner, "get_llm_config", lambda path: None)

    result = asyncio.run(manual_runner.run_manual_agent(make_request(), RUN_ID))

    assert result == failed_run(RUN_ID, "model_error")


@pytest.mark.parametrize("timeout", ["invalid", "0", "-1", "nan", "inf"])
def test_invalid_timeout_returns_safe_model_error(monkeypatch, timeout):
    monkeypatch.setattr(
        manual_runner,
        "get_llm_config",
        lambda path: SimpleNamespace(
            provider="deepseek",
            api_key="PRIVATE_API_KEY",
            model="offline",
        ),
    )
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", timeout)
    result = asyncio.run(manual_runner.run_manual_agent(make_request(), RUN_ID))

    assert result == failed_run(RUN_ID, "model_error")
    assert "PRIVATE_API_KEY" not in json.dumps(result.model_dump(), default=str)


def test_result_from_agent_state_builds_success_result():
    events = []
    record_run_finished(events, str(RUN_ID), "completed")
    result_sink = {
        "final_output": {
            "status": "completed",
            "facts": [{"text": "教学事实", "evidence_ids": ["E1"]}],
            "inferences": [],
            "missing_information": [],
            "data_mode": "fixture",
        }
    }

    result = result_from_agent_state(RUN_ID, events, result_sink)

    assert result.status == "completed"
    assert result.result.model_dump() == result_sink["final_output"]
    assert result.error is None


def test_result_from_agent_state_preserves_known_safe_failure():
    events = []
    record_run_finished(events, str(RUN_ID), "failed", "model_timeout")

    result = result_from_agent_state(RUN_ID, events, {})

    assert result == failed_run(RUN_ID, "model_timeout")


@pytest.mark.parametrize(
    ("events", "result_sink"),
    [
        ([], {}),
        ([{"type": "run_finished", "run_id": str(RUN_ID), "status": "failed"}], {}),
        (
            [{"type": "run_finished", "run_id": str(RUN_ID), "status": "completed"}],
            {"final_output": {"private": "PRIVATE_DETAIL"}},
        ),
    ],
)
def test_result_from_agent_state_hides_invalid_internal_state(events, result_sink):
    result = result_from_agent_state(RUN_ID, events, result_sink)

    assert result == failed_run(RUN_ID, "model_error")
    assert "PRIVATE_DETAIL" not in result.model_dump_json()


def test_runner_returns_failure_recorded_by_model_loop(monkeypatch):
    closed = configure_runner(monkeypatch)

    async def fake_model_loop(*args, events, run_id, **kwargs):
        record_run_finished(events, run_id, "failed", "model_timeout")
        return 1

    monkeypatch.setattr(manual_runner, "model_loop", fake_model_loop)

    result = asyncio.run(manual_runner.run_manual_agent(make_request(), RUN_ID))

    assert result == failed_run(RUN_ID, "model_timeout")
    assert closed == [True]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ReadTimeout("PRIVATE_DETAIL"), "model_timeout"),
        (RuntimeError("PRIVATE_DETAIL"), "model_error"),
    ],
)
def test_runner_maps_raised_model_error_without_leaking_details(
    monkeypatch,
    error,
    expected,
):
    closed = configure_runner(monkeypatch)

    async def fake_model_loop(*args, **kwargs):
        raise error

    monkeypatch.setattr(manual_runner, "model_loop", fake_model_loop)

    result = asyncio.run(manual_runner.run_manual_agent(make_request(), RUN_ID))

    assert result == failed_run(RUN_ID, expected)
    assert "PRIVATE_DETAIL" not in result.model_dump_json()
    assert closed == [True]


def test_runner_total_timeout_returns_safe_result_after_closing_client(monkeypatch):
    closed = configure_runner(monkeypatch)
    monkeypatch.setattr(manual_runner, "TASK_TIMEOUT_SECONDS", 0.005)

    async def fake_model_loop(*args, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(manual_runner, "model_loop", fake_model_loop)

    result = asyncio.run(manual_runner.run_manual_agent(make_request(), RUN_ID))

    assert result == failed_run(RUN_ID, "total_timeout")
    assert closed == [True]


def test_runner_cancellation_propagates_after_closing_client(monkeypatch):
    closed = configure_runner(monkeypatch)

    async def fake_model_loop(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(manual_runner, "model_loop", fake_model_loop)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(manual_runner.run_manual_agent(make_request(), RUN_ID))

    assert closed == [True]
