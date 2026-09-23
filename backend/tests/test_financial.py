from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import Numeric

from stock_agent.documents.sec_provider import UnknownTickerError
from stock_agent.financial import provider, service
from stock_agent.financial.parsing import (
    filter_facts_as_of,
    get_concept_entries,
    get_fact_duration_days,
    is_annual_duration_fact,
    is_quarterly_duration_fact,
    parse_financial_fact,
)
from stock_agent.financial.provider import build_company_facts_url
from stock_agent.storage.tables import financial_facts


CONCEPT = "RevenueFromContractWithCustomerExcludingAssessedTax"


def build_entry(
    *,
    start: str = "2026-01-26",
    end: str = "2026-04-26",
    filed: str = "2026-05-28",
    form: str = "10-Q",
    value: int = 18_775_000_000,
) -> dict:
    return {
        "start": start,
        "end": end,
        "val": value,
        "accn": "0001045810-26-000001",
        "form": form,
        "filed": filed,
        "fy": 2027,
        "fp": "Q1",
        "frame": "CY2026Q1",
    }


def build_company_facts(entries: list[dict]) -> dict:
    return {
        "facts": {
            "us-gaap": {
                CONCEPT: {
                    "units": {
                        "USD": entries,
                    },
                },
            },
        },
    }


def test_company_facts_provider_uses_existing_sec_http(monkeypatch):
    response = Mock()
    response.json.return_value = {"entityName": "NVIDIA CORP"}
    get_sec = Mock(return_value=response)
    client = Mock()
    monkeypatch.setattr(provider, "get_sec", get_sec)

    result = provider.get_company_facts_json(
        client=client,
        cik="1045810",
    )

    url = (
        "https://data.sec.gov/api/xbrl/companyfacts/"
        "CIK0001045810.json"
    )
    assert build_company_facts_url("1045810") == url
    get_sec.assert_called_once_with(url, client=client)
    assert result == {"entityName": "NVIDIA CORP"}


def test_parse_filter_and_period_helpers_preserve_exact_value():
    entry = build_entry()
    entries = get_concept_entries(
        build_company_facts([entry]),
        CONCEPT,
        "USD",
    )
    fact = parse_financial_fact(
        "NVDA",
        CONCEPT,
        "USD",
        entries[0],
    )

    assert fact.value == Decimal("18775000000")
    assert get_fact_duration_days(fact) == 91
    assert is_quarterly_duration_fact(fact)
    assert filter_facts_as_of([fact], date(2026, 5, 27)) == []
    assert filter_facts_as_of([fact], date(2026, 5, 28)) == [fact]

    amended_annual = parse_financial_fact(
        "NVDA",
        CONCEPT,
        "USD",
        build_entry(
            start="2025-01-01",
            end="2025-12-31",
            filed="2026-02-20",
            form="10-K/A",
        ),
    )
    assert is_annual_duration_fact(amended_annual)


def test_financial_fact_id_distinguishes_period_unit_and_value():
    base = parse_financial_fact("NVDA", CONCEPT, "USD", build_entry())
    different_period = parse_financial_fact(
        "NVDA",
        CONCEPT,
        "USD",
        build_entry(start="2025-07-28"),
    )
    different_unit = parse_financial_fact(
        "NVDA",
        CONCEPT,
        "shares",
        build_entry(),
    )
    different_value = parse_financial_fact(
        "NVDA",
        CONCEPT,
        "USD",
        build_entry(value=18_775_000_001),
    )

    assert len({
        base.fact_id,
        different_period.fact_id,
        different_unit.fact_id,
        different_value.fact_id,
    }) == 4


def test_financial_value_uses_exact_numeric_storage():
    assert isinstance(financial_facts.c.value.type, Numeric)


def test_financial_service_resolves_ticker_persists_and_filters(monkeypatch):
    entry = build_entry()
    future_entry = build_entry(
        start="2026-04-27",
        end="2026-07-26",
        filed="2026-08-27",
    )
    stored_fact = parse_financial_fact("NVDA", CONCEPT, "USD", entry)
    engine = Mock()
    client = Mock()

    ticker_to_cik = Mock(return_value="0001045810")
    get_company_facts = Mock(
        return_value=build_company_facts([entry, future_entry]),
    )
    save_facts = Mock(return_value=2)
    save_sync = Mock()
    query_facts = Mock(return_value=[stored_fact])

    monkeypatch.setattr(service, "ticker_to_cik", ticker_to_cik)
    monkeypatch.setattr(
        service,
        "get_financial_fact_sync",
        Mock(return_value=None),
    )
    monkeypatch.setattr(
        service,
        "get_company_facts_json",
        get_company_facts,
    )
    monkeypatch.setattr(service, "save_financial_facts", save_facts)
    monkeypatch.setattr(service, "save_financial_fact_sync", save_sync)
    monkeypatch.setattr(service, "query_financial_facts", query_facts)

    facts = service.get_financial_facts(
        engine=engine,
        client=client,
        company_id="nvda",
        concept=CONCEPT,
        unit="USD",
        as_of=date(2026, 8, 20),
        period_type="quarterly",
    )

    ticker_to_cik.assert_called_once_with("NVDA")
    get_company_facts.assert_called_once_with(
        client=client,
        cik="0001045810",
    )
    assert len(save_facts.call_args.kwargs["facts"]) == 2
    save_sync.assert_called_once()
    query_facts.assert_called_once_with(
        engine=engine,
        company_id="NVDA",
        concept=CONCEPT,
        unit="USD",
        as_of=date(2026, 8, 20),
    )
    assert facts == [stored_fact]


def test_financial_service_rejects_unknown_ticker(monkeypatch):
    monkeypatch.setattr(service, "ticker_to_cik", Mock(return_value=None))
    monkeypatch.setattr(
        service,
        "get_financial_fact_sync",
        Mock(return_value=None),
    )

    with pytest.raises(UnknownTickerError, match="SEC 未找到 ticker: UNKNOWN"):
        service.get_financial_facts(
            engine=Mock(),
            client=Mock(),
            company_id="unknown",
            concept=CONCEPT,
            unit="USD",
            as_of=date(2026, 8, 20),
        )


def test_financial_service_reuses_covered_cache_without_sec(monkeypatch):
    fact = parse_financial_fact("NVDA", CONCEPT, "USD", build_entry())
    engine = Mock()
    ticker_to_cik = Mock(
        side_effect=AssertionError("covered cache must not resolve ticker")
    )
    monkeypatch.setattr(service, "ticker_to_cik", ticker_to_cik)
    monkeypatch.setattr(
        service,
        "get_financial_fact_sync",
        Mock(return_value={"covered_through": date(2026, 9, 20)}),
    )
    monkeypatch.setattr(
        service,
        "query_financial_facts",
        Mock(return_value=[fact]),
    )

    result = service.get_financial_facts(
        engine=engine,
        client=Mock(),
        company_id="NVDA",
        concept=CONCEPT,
        unit="USD",
        as_of=date(2026, 9, 20),
        period_type="quarterly",
    )

    assert result == [fact]
    ticker_to_cik.assert_not_called()
