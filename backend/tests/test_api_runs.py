"""D06 Step 6：使用依赖替换离线测试 POST /api/runs 边界。"""

import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from stock_agent.api.app import create_app
from stock_agent.api.dependencies import get_agent_runner
from stock_agent.api.schemas import AgentRunResult
from stock_agent.schemas.errors import ErrorCode, make_public_error
from stock_agent.schemas.research_output import ResearchOutput


BACKEND = Path(__file__).resolve().parents[1]
MISSING = object()


def valid_payload() -> dict[str, object]:
    """返回每个测试独享的合法 fixture 请求，避免测试之间共享可变字典。"""
    return {
        "company_id": "NVDA",
        "question": "查询教学模拟报价和公司介绍",
        "data_mode": "fixture",
        "as_of": "2026-09-15T16:00:00+08:00",
    }


def completed_result(run_id: UUID) -> AgentRunResult:
    """构造包含证据 ID 的离线成功结果。"""
    output = ResearchOutput(
        status="completed",
        facts=[
            {
                "text": "NVDA 是本地 fixture 中的教学公司。",
                "evidence_ids": ["company:NVDA"],
            }
        ],
        inferences=[],
        missing_information=[],
        data_mode="fixture",
    )
    return AgentRunResult(
        run_id=run_id,
        status="completed",
        result=output,
        error=None,
    )


def failed_result(run_id: UUID, code: ErrorCode) -> AgentRunResult:
    """构造只含固定 PublicError 的离线失败结果。"""
    return AgentRunResult(
        run_id=run_id,
        status="failed",
        result=None,
        error=make_public_error(code),
    )


def client_for(runner) -> TestClient:
    """创建独立应用，并把生产 runner 替换为当前测试的离线函数。"""
    application = create_app()
    application.dependency_overrides[get_agent_runner] = lambda: runner
    return TestClient(application)


def test_normal_request_returns_structured_success():
    calls = []

    async def runner(request, run_id):
        calls.append((request, run_id))
        return completed_result(run_id)

    with client_for(runner) as client:
        response = client.post("/api/runs", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert UUID(body["run_id"]) == calls[0][1]
    assert body["status"] == "completed"
    assert body["error"] is None
    assert body["result"]["status"] == "completed"
    assert len(calls) == 1
    assert calls[0][0].company_id == "NVDA"


def test_two_requests_use_unique_matching_run_ids():
    received_run_ids = []

    async def runner(request, run_id):
        received_run_ids.append(run_id)
        return completed_result(run_id)

    with client_for(runner) as client:
        first = client.post("/api/runs", json=valid_payload())
        second = client.post("/api/runs", json=valid_payload())

    response_run_ids = [UUID(first.json()["run_id"]), UUID(second.json()["run_id"])]
    assert response_run_ids == received_run_ids
    assert response_run_ids[0] != response_run_ids[1]


@pytest.mark.parametrize(
    "value",
    [MISSING, "", "   ", "x" * 2001],
    ids=["missing", "empty", "whitespace", "too-long"],
)
def test_invalid_question_returns_422_without_calling_runner(value):
    calls = []

    async def runner(request, run_id):
        calls.append((request, run_id))
        return completed_result(run_id)

    payload = valid_payload()
    if value is MISSING:
        payload.pop("question")
    else:
        payload["question"] = value

    with client_for(runner) as client:
        response = client.post("/api/runs", json=payload)

    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize(
    "value",
    [MISSING, "", "   ", "x" * 81],
    ids=["missing", "empty", "whitespace", "too-long"],
)
def test_invalid_company_id_returns_422_without_calling_runner(value):
    calls = []

    async def runner(request, run_id):
        calls.append((request, run_id))
        return completed_result(run_id)

    payload = valid_payload()
    if value is MISSING:
        payload.pop("company_id")
    else:
        payload["company_id"] = value

    with client_for(runner) as client:
        response = client.post("/api/runs", json=payload)

    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("data_mode", "paper"),
        ("as_of", "2026-09-15T16:00:00"),
    ],
    ids=["invalid-data-mode", "as-of-without-timezone"],
)
def test_invalid_mode_or_as_of_returns_422_without_calling_runner(field, value):
    calls = []

    async def runner(request, run_id):
        calls.append((request, run_id))
        return completed_result(run_id)

    payload = valid_payload()
    payload[field] = value

    with client_for(runner) as client:
        response = client.post("/api/runs", json=payload)

    assert response.status_code == 422
    assert calls == []


def test_extra_request_field_returns_422_without_calling_runner():
    calls = []

    async def runner(request, run_id):
        calls.append((request, run_id))
        return completed_result(run_id)

    payload = valid_payload()
    payload["api_key"] = "PRIVATE_API_KEY"

    with client_for(runner) as client:
        response = client.post("/api/runs", json=payload)

    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize("code", ["model_error", "model_timeout", "total_timeout"])
def test_known_agent_failure_returns_only_fixed_public_error(code):
    async def runner(request, run_id):
        return failed_result(run_id, code)

    with client_for(runner) as client:
        response = client.post("/api/runs", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "run_id": body["run_id"],
        "status": "failed",
        "result": None,
        "error": make_public_error(code).model_dump(),
    }
    UUID(body["run_id"])


def test_runner_exception_is_hidden_from_response():
    private_values = [
        "private_api_key",
        "authorization",
        "private_provider_error",
        "traceback",
    ]

    async def runner(request, run_id):
        raise RuntimeError("PRIVATE_API_KEY Authorization PRIVATE_PROVIDER_ERROR")

    with client_for(runner) as client:
        response = client.post("/api/runs", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    serialized = json.dumps(body, ensure_ascii=False).casefold()
    assert body["status"] == "failed"
    assert body["error"] == make_public_error("model_error").model_dump()
    assert all(private not in serialized for private in private_values)


def test_mismatched_runner_id_returns_generated_id_and_safe_error():
    received_run_ids = []

    async def runner(request, run_id):
        received_run_ids.append(run_id)
        return completed_result(uuid4())

    with client_for(runner) as client:
        response = client.post("/api/runs", json=valid_payload())

    body = response.json()
    assert response.status_code == 200
    assert UUID(body["run_id"]) == received_run_ids[0]
    assert body["status"] == "failed"
    assert body["error"] == make_public_error("model_error").model_dump()


def test_fixture_response_preserves_data_mode_and_evidence_ids():
    async def runner(request, run_id):
        return completed_result(run_id)

    with client_for(runner) as client:
        response = client.post("/api/runs", json=valid_payload())

    result = response.json()["result"]
    assert result["data_mode"] == "fixture"
    assert result["data_mode"] != "live"
    assert result["facts"][0]["evidence_ids"] == ["company:NVDA"]


def test_importing_app_does_not_call_runner_or_create_http_client():
    """在独立解释器导入 app，避免本测试进程的模块缓存掩盖副作用。"""
    script = """
import httpx
from unittest.mock import patch

import stock_agent.agents.manual_runner as manual_runner

runner_called = False

def forbidden_runner(*args, **kwargs):
    global runner_called
    runner_called = True
    raise AssertionError("runner must not run during import")

manual_runner.run_manual_agent = forbidden_runner

with patch.object(
    httpx,
    "AsyncClient",
    side_effect=AssertionError("HTTP client must not be created during import"),
):
    from stock_agent.api.app import app

assert not runner_called
assert any(route.path == "/api/runs" for route in app.routes)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(BACKEND / "src")

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
