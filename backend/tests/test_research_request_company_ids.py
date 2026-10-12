"""ResearchRequest multi-security contract tests."""

from datetime import datetime, timezone

from pydantic import ValidationError
import pytest

from stock_agent.schemas.research import ResearchRequest


def make_request(**updates: object) -> ResearchRequest:
    values = {
        "company_ids": ["NVDA", "AAPL"],
        "question": "比较两家公司",
        "data_mode": "mixed",
        "as_of": datetime(2026, 10, 12, tzinfo=timezone.utc),
    }
    values.update(updates)
    return ResearchRequest.model_validate(values)


def test_request_accepts_multiple_company_ids_in_order() -> None:
    request = make_request()

    assert request.company_ids == ["NVDA", "AAPL"]


def test_request_defaults_to_no_company_ids() -> None:
    request = make_request(company_ids=[])

    assert request.company_ids == []


def test_legacy_company_id_field_is_rejected() -> None:
    with pytest.raises(ValidationError) as error:
        make_request(company_ids=[], company_id="NVDA")

    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_request_rejects_more_than_twenty_company_ids() -> None:
    with pytest.raises(ValidationError) as error:
        make_request(company_ids=[f"TICKER-{index}" for index in range(21)])

    assert error.value.errors()[0]["type"] == "too_long"
