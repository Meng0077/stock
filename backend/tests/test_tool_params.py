"""把原手工案例改成参数化测试：每组参数都是一个独立案例。"""

import pytest
from pydantic import ValidationError

from stock_agent.schemas.tool_params import CompanyToolParams


@pytest.mark.parametrize("company_id,expected", [
    ("NVDA", "NVDA"),
    ("  NVDA  ", "NVDA"),
    ("AAPL", "AAPL"),
    ("A" * 80, "A" * 80),
])
def test_valid_company_id(company_id, expected):
    result = CompanyToolParams.model_validate({"company_id": company_id})
    assert result.company_id == expected


@pytest.mark.parametrize("payload,field,error_type", [
    ({"company_id": "   "}, "company_id", "string_too_short"),
    ({}, "company_id", "missing"),
    ({"company_id": "NVDA", "extra": 1}, "extra", "extra_forbidden"),
    ({"company_id": "A" * 81}, "company_id", "string_too_long"),
    ({"company_id": None}, "company_id", "string_type"),
])
def test_invalid_parameters(payload, field, error_type):
    # 预期抛错也属于测试通过；同时检查错误位置和类别。
    with pytest.raises(ValidationError) as caught:
        CompanyToolParams.model_validate(payload)
    errors = caught.value.errors(include_input=False)
    assert any(e["loc"] == (field,) and e["type"] == error_type for e in errors)


def test_invalid_assignment_preserves_previous_value():
    request = CompanyToolParams(company_id="NVDA")
    with pytest.raises(ValidationError):
        request.company_id = " "
    assert request.company_id == "NVDA"
