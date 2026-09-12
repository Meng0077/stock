"""固定工具的业务边界与返回值隔离；不访问网络。"""

from datetime import datetime

import pytest

from stock_agent.tools.company import get_company_profile
from stock_agent.tools.quote import get_quote


@pytest.mark.parametrize("tool,time_field", [
    (get_company_profile, "as_of"),
    (get_quote, "quoted_at"),
])
def test_fixture_metadata(tool, time_field):
    result = tool("NVDA")
    assert result["company_id"] == "NVDA"
    assert result["data_mode"] == "fixture"
    assert result["source"] == "本地教学模拟数据"
    assert datetime.fromisoformat(result[time_field]).utcoffset() is not None


@pytest.mark.parametrize("tool", [get_company_profile, get_quote])
def test_unsupported_company(tool):
    with pytest.raises(ValueError, match="不支持的公司标识"):
        tool("AAPL")


@pytest.mark.parametrize("tool", [get_company_profile, get_quote])
def test_returned_data_is_independent(tool):
    first = tool("NVDA")
    first["company_id"] = "changed"
    assert tool("NVDA")["company_id"] == "NVDA"


def test_quote_is_fixed_simulation():
    result = get_quote("NVDA")
    assert result["price"] == 100.0
    assert result["currency"] == "USD"
    assert "虚构" in result["note"]


def test_company_has_description():
    result = get_company_profile("NVDA")
    assert result["company_name"].strip()
    assert result["description"].strip()
