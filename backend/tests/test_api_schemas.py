"""D06 Step 3：API 契约测试；不调用模型、不启动 HTTP 服务。"""

from uuid import UUID

import pytest
from pydantic import ValidationError

from stock_agent.api.schemas import AgentRunResult, RunResponse
from stock_agent.schemas.errors import make_public_error
from stock_agent.schemas.research_output import EvidenceClaim, ResearchOutput


RUN_ID = UUID("12345678-1234-5678-1234-567812345678")


def completed_output() -> ResearchOutput:
    return ResearchOutput(
        status="completed",
        facts=[EvidenceClaim(text="教学事实", evidence_ids=["E1"])],
        inferences=[],
        missing_information=[],
        data_mode="fixture",
    )


def insufficient_output() -> ResearchOutput:
    return ResearchOutput(
        status="insufficient_information",
        facts=[],
        inferences=[],
        missing_information=["缺少资料"],
        data_mode="fixture",
    )


@pytest.mark.parametrize(
    ("status", "result"),
    [
        ("completed", completed_output()),
        ("insufficient_information", insufficient_output()),
    ],
)
def test_successful_terminal_status_requires_matching_result(status, result):
    run = AgentRunResult(run_id=RUN_ID, status=status, result=result)

    assert run.status == status
    assert run.result == result
    assert run.error is None


@pytest.mark.parametrize("status", ["completed", "insufficient_information"])
def test_successful_terminal_status_rejects_missing_result(status):
    with pytest.raises(ValidationError, match="必须有 result"):
        AgentRunResult(run_id=RUN_ID, status=status)


def test_successful_terminal_status_rejects_error():
    with pytest.raises(ValidationError, match="必须有 result"):
        AgentRunResult(
            run_id=RUN_ID,
            status="completed",
            result=completed_output(),
            error=make_public_error("model_error"),
        )


@pytest.mark.parametrize(
    ("status", "error_code"),
    [("failed", "model_error"), ("cancelled", "cancelled")],
)
def test_failed_or_cancelled_status_requires_matching_error(status, error_code):
    run = AgentRunResult(
        run_id=RUN_ID,
        status=status,
        error=make_public_error(error_code),
    )

    assert run.result is None
    assert run.error.code == error_code


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_or_cancelled_status_rejects_missing_error(status):
    with pytest.raises(ValidationError, match="必须有 error"):
        AgentRunResult(run_id=RUN_ID, status=status)


def test_failed_status_rejects_result():
    with pytest.raises(ValidationError, match="必须没有 result"):
        AgentRunResult(
            run_id=RUN_ID,
            status="failed",
            result=completed_output(),
            error=make_public_error("model_error"),
        )


def test_outer_status_must_match_research_output_status():
    with pytest.raises(ValidationError, match="外层 status"):
        AgentRunResult(
            run_id=RUN_ID,
            status="completed",
            result=insufficient_output(),
        )


@pytest.mark.parametrize(
    ("status", "error_code"),
    [("cancelled", "model_error"), ("failed", "cancelled")],
)
def test_cancelled_status_and_error_code_must_appear_together(status, error_code):
    with pytest.raises(ValidationError, match="必须同时出现"):
        AgentRunResult(
            run_id=RUN_ID,
            status=status,
            error=make_public_error(error_code),
        )


def test_response_explicitly_copies_only_public_fields():
    class RichAgentRunResult(AgentRunResult):
        internal_trace: str

    run = RichAgentRunResult(
        run_id=RUN_ID,
        status="completed",
        result=completed_output(),
        internal_trace="PRIVATE_INTERNAL_TRACE",
    )

    response = RunResponse.from_agent_result(run)

    assert type(response) is RunResponse
    assert response.run_id == run.run_id
    assert response.status == run.status
    assert response.result == run.result
    assert response.error is None
    assert set(response.model_dump()) == {"run_id", "status", "result", "error"}
    assert "PRIVATE_INTERNAL_TRACE" not in response.model_dump_json()
