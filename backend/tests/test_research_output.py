"""D04 Task 2：用本地样例检查研究结果的 JSON 解析。"""

import pytest
from pydantic import ValidationError

from stock_agent.schemas.research_output import ResearchOutput


VALID_JSON = """{
    "status": "completed",
    "facts": [{"text": "报价为 100 元", "evidence_ids": ["quote-1"]}],
    "inferences": [],
    "missing_information": [],
    "data_mode": "fixture"
}"""

MISSING_FIELD_JSON = """{
    "status": "completed",
    "facts": [{"text": "报价为 100 元", "evidence_ids": ["quote-1"]}],
    "inferences": [],
    "missing_information": []
}"""


def test_valid_json_parses():
    result = ResearchOutput.model_validate_json(VALID_JSON)

    assert result.status == "completed"
    assert result.facts[0].text == "报价为 100 元"
    assert result.facts[0].evidence_ids == ["quote-1"]
    assert result.data_mode == "fixture"


def test_no_evidence_requires_explicit_null_data_mode():
    result = ResearchOutput.model_validate({
        "status": "insufficient_information",
        "facts": [],
        "inferences": [],
        "missing_information": ["缺少资料"],
        "data_mode": None,
    })

    assert result.data_mode is None


@pytest.mark.parametrize(
    ("raw_json", "field", "error_type"),
    [
        pytest.param('{"status":', (), "json_invalid", id="malformed-json"),
        pytest.param(MISSING_FIELD_JSON, ("data_mode",), "missing", id="missing-field"),
        pytest.param(f"```json\n{VALID_JSON}\n```", (), "json_invalid", id="code-fence"),
    ],
)
def test_invalid_json_is_rejected(raw_json, field, error_type):
    with pytest.raises(ValidationError) as caught:
        ResearchOutput.model_validate_json(raw_json)

    assert any(
        error["loc"] == field and error["type"] == error_type
        for error in caught.value.errors(include_input=False)
    )
