from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from stock_agent.documents.schemas import FilingFile, FilingMetadata
from stock_agent.market import earnings
from stock_agent.market.earnings import (
    EarningsReleaseEvent,
    get_earnings_releases,
    get_latest_earnings_release,
    is_earnings_8k,
    research_earnings_reaction,
)
from stock_agent.market.errors import MarketDataProviderError
from stock_agent.market_reaction.models import MarketReactionResult
from stock_agent.market_reaction import service


def make_filing(
    *,
    accession_number: str = "0001045810-26-000100",
    accepted_at: datetime | None = None,
) -> FilingMetadata:
    accepted_at = accepted_at or datetime(
        2026,
        9,
        11,
        20,
        5,
        tzinfo=timezone.utc,
    )
    return FilingMetadata(
        company_id="NVDA",
        cik="0001045810",
        form="8-K",
        filing_date=accepted_at.date(),
        report_date=date(2026, 7, 26),
        accepted_at=accepted_at,
        accession_number=accession_number,
        primary_document="nvda-20260911.htm",
        document_url="https://www.sec.gov/example.htm",
    )


def make_primary_file(filing: FilingMetadata) -> FilingFile:
    return FilingFile(
        sequence="1",
        document_name=filing.primary_document,
        document_type="8-K",
        description="Current report",
        document_url=filing.document_url,
        is_primary=True,
    )


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("Item 2.02 Results of Operations", True),
        ("Results of Operations and Financial Condition", True),
        ("Item 5.02 Departure of Directors", False),
    ],
)
def test_is_earnings_8k_uses_primary_filing_content(
    monkeypatch,
    content,
    expected,
):
    filing = make_filing()
    primary_file = make_primary_file(filing)
    monkeypatch.setattr(
        earnings,
        "get_filing_files",
        Mock(return_value=[primary_file]),
    )
    load_document = Mock(
        return_value=SimpleNamespace(content=content)
    )
    monkeypatch.setattr(
        earnings,
        "load_filing_document",
        load_document,
    )

    assert is_earnings_8k(filing) is expected
    load_document.assert_called_once_with(
        filing=filing,
        filing_file=primary_file,
    )


def test_is_earnings_8k_requires_primary_file(monkeypatch):
    monkeypatch.setattr(
        earnings,
        "get_filing_files",
        Mock(return_value=[]),
    )
    load_document = Mock()
    monkeypatch.setattr(
        earnings,
        "load_filing_document",
        load_document,
    )

    assert is_earnings_8k(make_filing()) is False
    load_document.assert_not_called()


def test_latest_earnings_release_skips_non_earnings_8k(monkeypatch):
    as_of = datetime(2026, 9, 14, 16, tzinfo=timezone.utc)
    other = make_filing(
        accession_number="0001045810-26-000101",
        accepted_at=datetime(2026, 9, 12, 20, tzinfo=timezone.utc),
    )
    target = make_filing()
    get_recent = Mock(return_value=[other, target])
    classify = Mock(side_effect=[False, True])
    monkeypatch.setattr(earnings, "get_recent_filings", get_recent)
    monkeypatch.setattr(earnings, "is_earnings_8k", classify)

    result = get_latest_earnings_release(
        symbol=" nvda ",
        as_of=as_of,
    )

    get_recent.assert_called_once_with(
        company_id="NVDA",
        as_of=as_of,
        forms={"8-K"},
        limit=earnings.EARNINGS_8K_SCAN_LIMIT,
    )
    assert classify.call_args_list == [
        call(other),
        call(target),
    ]
    assert result == EarningsReleaseEvent(
        event_id=(
            "earnings:NVDA:"
            "0001045810-26-000100"
        ),
        symbol="NVDA",
        released_at=target.accepted_at,
        released_at_source="sec_8k_accepted_at",
        report_date=target.report_date,
        accession_number=target.accession_number,
        source_url=target.document_url,
        warnings=("event_time_uses_sec_8k_acceptance",),
    )


def test_earnings_history_scans_candidates_and_respects_before(monkeypatch):
    filings = [
        make_filing(
            accession_number=f"0001045810-26-00010{index}",
            accepted_at=datetime(
                2026,
                9,
                day,
                20,
                tzinfo=timezone.utc,
            ),
        )
        for index, day in enumerate((12, 10, 9, 8))
    ]
    get_recent = Mock(return_value=filings)
    classify = Mock(side_effect=[False, True])
    monkeypatch.setattr(earnings, "get_recent_filings", get_recent)
    monkeypatch.setattr(earnings, "is_earnings_8k", classify)

    result = get_earnings_releases(
        symbol=" nvda ",
        as_of=datetime(2026, 9, 14, tzinfo=timezone.utc),
        before=datetime(2026, 9, 11, tzinfo=timezone.utc),
        limit=1,
    )

    get_recent.assert_called_once_with(
        company_id="NVDA",
        as_of=datetime(2026, 9, 14, tzinfo=timezone.utc),
        forms={"8-K"},
        limit=earnings.EARNINGS_8K_SCAN_LIMIT,
    )
    assert classify.call_args_list == [call(filings[1]), call(filings[2])]
    assert [item.accession_number for item in result] == [
        filings[2].accession_number
    ]


def test_earnings_history_requires_aware_before() -> None:
    with pytest.raises(ValueError, match="before must be timezone-aware"):
        get_earnings_releases(
            symbol="NVDA",
            as_of=datetime(2026, 9, 14, tzinfo=timezone.utc),
            before=datetime(2026, 9, 11),
            limit=3,
        )


def test_research_earnings_reaction_uses_generic_timed_service(
    monkeypatch,
):
    event_at = datetime(2026, 9, 11, 20, 5, tzinfo=timezone.utc)
    as_of = event_at + timedelta(hours=2)
    event = EarningsReleaseEvent(
        event_id="earnings:NVDA:0001045810-26-000100",
        symbol="NVDA",
        released_at=event_at,
        released_at_source="sec_8k_accepted_at",
        report_date=date(2026, 7, 26),
        accession_number="0001045810-26-000100",
        source_url="https://www.sec.gov/example.htm",
        warnings=("event_time_uses_sec_8k_acceptance",),
    )
    provider = Mock()
    expected = Mock(spec=MarketReactionResult)
    research = Mock(return_value=expected)
    monkeypatch.setattr(
        earnings,
        "research_timed_event_reaction",
        research,
    )

    result = research_earnings_reaction(
        earnings=event,
        symbol="NVDA",
        provider=provider,
        as_of=as_of,
    )

    assert result is expected
    research.assert_called_once_with(
        event_id=event.event_id,
        event_type="earnings",
        event_at=event_at,
        event_time_source="sec_8k_accepted_at",
        symbol="NVDA",
        provider=provider,
        as_of=as_of,
        extra_issues=["event_time_uses_sec_8k_acceptance"],
    )


def test_timed_event_service_preserves_structured_provider_failure(
    monkeypatch,
):
    event_at = datetime(2026, 9, 11, 20, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(
        service,
        "prepare_timed_event_market_data",
        Mock(side_effect=MarketDataProviderError("unavailable")),
    )

    result = service.research_timed_event_reaction(
        event_id="earnings:NVDA:0001045810-26-000100",
        event_type="earnings",
        event_at=event_at,
        event_time_source="sec_8k_accepted_at",
        symbol=" nvda ",
        provider=Mock(),
        as_of=event_at + timedelta(hours=2),
        extra_issues=["event_time_uses_sec_8k_acceptance"],
    )

    assert result.release_id == (
        "earnings:NVDA:0001045810-26-000100"
    )
    assert result.release_type == "earnings"
    assert result.symbol == "NVDA"
    assert result.event_at == event_at
    assert result.reference_price is None
    assert result.observations == {}
    assert result.issues == [
        "minute_data_provider_error",
        "event_time_uses_sec_8k_acceptance",
    ]
    assert result.event_time_source == "sec_8k_accepted_at"
