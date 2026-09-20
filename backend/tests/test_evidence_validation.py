"""D04 Task 3：校验本次提供的证据 ID 与资料模式。"""

import json

import pytest
from langchain.messages import ToolMessage

from stock_agent.agents.structured_output import (
    EvidenceValidationError,
    collect_evidence_data_modes,
    collect_evidence_ids,
    resolve_output_data_mode,
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
    output = make_output(status="insufficient_information", data_mode=None)

    assert validate_evidence(output, set(), {}, "fixture") is output


def test_all_claim_ids_must_belong_to_this_run():
    output = make_output(
        facts=[{"text": "报价为 100 元", "evidence_ids": ["E1", "E2"]}],
        inferences=[{"text": "价格可能波动", "evidence_ids": ["E2"]}],
    )

    evidence_modes = {"E1": "fixture", "E2": "fixture"}
    assert validate_evidence(output, {"E1", "E2"}, evidence_modes, "fixture") is output

    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence(output, {"E1"}, evidence_modes, "fixture")
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
        validate_evidence(output, set(), {}, "fixture")
    assert caught.value.code == "unknown_evidence_id"


def test_model_cannot_label_fixture_data_as_live():
    output = make_output(
        facts=[{"text": "报价为 100 元", "evidence_ids": ["E1"]}],
        data_mode="live",
    )

    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence(output, {"E1"}, {"E1": "fixture"}, "fixture")
    assert caught.value.code == "data_mode_mismatch"


def test_rag_and_quote_evidence_can_be_used_in_the_same_result():
    rag_ids = ["rag:NVDA:nvda.txt:1", "rag:NVDA:nvda.txt:2"]
    messages = [
        ToolMessage(
            name="retrieve_knowledge",
            tool_call_id="call_rag",
            content=json.dumps([
                {"evidence_id": evidence_id, "data_mode": "historical"}
                for evidence_id in rag_ids
            ]),
        ),
        ToolMessage(
            name="get_quote",
            tool_call_id="call_quote",
            content=json.dumps({"evidence_id": "E-quote", "data_mode": "fixture"}),
        ),
    ]
    allowed_ids = collect_evidence_ids(messages)
    assert allowed_ids == {*rag_ids, "E-quote"}

    output = make_output(data_mode="mixed", facts=[
        {"text": "公司业务事实", "evidence_ids": rag_ids},
        {"text": "教学报价", "evidence_ids": ["E-quote"]},
    ])
    evidence_modes = collect_evidence_data_modes(messages)
    expected_mode = resolve_output_data_mode(output, evidence_modes)
    assert expected_mode == "mixed"
    assert validate_evidence(output, allowed_ids, evidence_modes, "mixed") is output

    unknown_output = make_output(facts=[
        {"text": "未提供的片段", "evidence_ids": ["rag:NVDA:nvda.txt:99"]},
    ])
    with pytest.raises(EvidenceValidationError):
        validate_evidence(unknown_output, allowed_ids, evidence_modes, "mixed")


def test_request_mode_rejects_historical_evidence_in_fixture_run():
    output = make_output(
        facts=[{"text": "SEC filing fact", "evidence_ids": ["rag:1"]}],
        data_mode="historical",
    )

    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence(
            output,
            {"rag:1"},
            {"rag:1": "historical"},
            "fixture",
        )

    assert caught.value.code == "data_mode_not_allowed"


def test_same_evidence_id_cannot_have_conflicting_data_modes():
    messages = [
        ToolMessage(
            name="get_quote",
            tool_call_id="call_fixture",
            content=json.dumps({"evidence_id": "E1", "data_mode": "fixture"}),
        ),
        ToolMessage(
            name="retrieve_knowledge",
            tool_call_id="call_historical",
            content=json.dumps({"evidence_id": "E1", "data_mode": "historical"}),
        ),
    ]

    with pytest.raises(EvidenceValidationError) as caught:
        collect_evidence_data_modes(messages)

    assert caught.value.code == "evidence_data_mode_conflict"


def test_single_evidence_cannot_have_mixed_data_mode():
    messages = [
        ToolMessage(
            name="get_quote",
            tool_call_id="call-1",
            content=json.dumps({"evidence_id": "E1", "data_mode": "mixed"}),
        )
    ]

    with pytest.raises(EvidenceValidationError) as caught:
        collect_evidence_data_modes(messages)

    assert caught.value.code == "evidence_data_mode_invalid"


def test_request_mode_rejects_uncited_evidence_from_another_mode():
    output = make_output(status="insufficient_information", data_mode=None)

    with pytest.raises(EvidenceValidationError) as caught:
        validate_evidence(
            output,
            {"E-historical"},
            {"E-historical": "historical"},
            "fixture",
        )

    assert caught.value.code == "data_mode_not_allowed"


def test_failed_rag_and_structured_output_do_not_supply_evidence():
    messages = [
        ToolMessage(
            name="retrieve_knowledge",
            tool_call_id="call_failed_rag",
            status="error",
            content=json.dumps([{"evidence_id": "rag:failed"}]),
        ),
        ToolMessage(
            name="ResearchOutput",
            tool_call_id="call_output",
            content=json.dumps({"evidence_id": "E-model-invented"}),
        ),
    ]
    assert collect_evidence_ids(messages) == set()
