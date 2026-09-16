"""D04 Task 3：校验本次提供的证据 ID 与资料模式。"""

import pytest

from stock_agent.agents.structured_output import (
    EvidenceValidationError,
    validate_evidence,
)
from stock_agent.schemas.research_output import ResearchOutput


def make_output(*, facts=None, inferences=None, status="completed", data_mode="fixture"):
    return ResearchOutput.model_validate(
        {
            "status": status,
            "facts": facts or [],
            "inferences": inferences or [],
            "missing_information": ["尚未取得报价"] if status == "insufficient_information" else [],
            "data_mode": data_mode,
        }
    )


def test_no_evidence_allows_explicit_insufficient_information():
    output = make_output(status="insufficient_information")

    assert validate_evidence(output, set(), "fixture") is output


def test_all_claim_ids_must_belong_to_this_run():
    output = make_output(
        facts=[{"text": "报价为 100 元", "evidence_ids": ["E1", "E2"]}],
        inferences=[{"text": "价格可能波动", "evidence_ids": ["E2"]}],
    )

    assert validate_evidence(output, {"E1", "E2"}, "fixture") is output

    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence(output, {"E1"}, "fixture")
    assert caught.value.code == "unknown_evidence_id"


@pytest.mark.parametrize(
    ("status", "facts", "inferences"),
    [
        ("completed", [{"text": "报价为 100 元", "evidence_ids": ["E1"]}], []),
        (
            "insufficient_information",
            [],
            [{"text": "价格可能波动", "evidence_ids": ["E1"]}],
        ),
    ],
)
def test_empty_allowed_ids_rejects_any_claim(status, facts, inferences):
    output = make_output(status=status, facts=facts, inferences=inferences)

    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence(output, set(), "fixture")
    assert caught.value.code == "unknown_evidence_id"


def test_model_cannot_label_fixture_data_as_live():
    output = make_output(
        facts=[{"text": "报价为 100 元", "evidence_ids": ["E1"]}],
        data_mode="live",
    )

    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence(output, {"E1"}, "fixture")
    assert caught.value.code == "data_mode_mismatch"
