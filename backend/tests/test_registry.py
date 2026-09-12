import pytest
from pydantic import ValidationError

from stock_agent.tools.registry import execute_tool

@pytest.mark.parametrize("tool_name,company_id", [
    ("get_quote", "NVDA"),
    ("get_company_profile", "NVDA"),
    ("get_quote", "  NVDA  "),
])

def test_execute_tool_valid(tool_name, company_id):
    result = execute_tool(tool_name, {"company_id": company_id})
    assert result["company_id"] == "NVDA"
    assert result["data_mode"] == "fixture"
    

@pytest.mark.parametrize("input,field,error_type", [
    ({"company_id": ''}, "company_id", "string_too_short"),
    ({"company_id": 'NVDA', "extra": 1}, "extra", "extra_forbidden"),
    ])

def test_execute_tool_invalid_params(input, field, error_type):
    with pytest.raises(ValidationError) as caught:
        execute_tool("get_quote", input)
    errors = caught.value.errors(include_input=False)
    assert any(e["loc"] == (field,) and e["type"] == error_type for e in errors)
    
def test_execute_tool_unknown_tool():
    with pytest.raises(ValueError, match="未知工具"):
        execute_tool("delete_file", {"company_id": "NVDA"})

def test_execute_tool_unsupported_company():
    with pytest.raises(ValueError, match="不支持的公司标识"):
        execute_tool("get_quote", {"company_id": "AAPL"})
        