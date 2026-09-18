from datetime import datetime, timezone

import pytest

from stock_agent.documents import sec_provider


@pytest.fixture
def recent(monkeypatch):
    recent = {
        "form": ["10-K"],
        "filingDate": ["2026-03-01"],
        "reportDate": ["2025-12-31"],
        "acceptanceDateTime": ["2026-03-01T12:00:00Z"],
        "accessionNumber": ["0000000001-26-000001"],
        "primaryDocument": ["annual.htm"],
    }
    monkeypatch.setattr(sec_provider, "ticker_to_cik", lambda company_id: "0000000001")
    monkeypatch.setattr(
        sec_provider,
        "get_company_submissions",
        lambda cik: {"filings": {"recent": recent}},
    )
    return recent


@pytest.mark.parametrize("form", sorted(sec_provider.SUPPORTED_FORMS))
def test_default_and_explicit_forms_include_foreign_issuers_and_amendments(recent, form):
    recent["form"] = [form]
    as_of = datetime.fromisoformat("2026-03-01T12:00:00+00:00")

    for forms in (None, {form}):
        filings = sec_provider.get_recent_filings("example", as_of, forms=forms)
        assert len(filings) == 1
        assert filings[0].form == form
        assert filings[0].company_id == "EXAMPLE"
        assert filings[0].accepted_at == as_of


def test_as_of_filters_before_sorting_and_limiting_with_timezone_conversion(recent):
    recent.update({
        "form": ["10-K", "10-K/A", "10-Q"],
        "filingDate": ["2026-03-01"] * 3,
        "reportDate": ["2025-12-31"] * 3,
        "acceptanceDateTime": [
            "2026-03-01T11:00:00Z",
            "2026-03-01T13:00:00Z",
            "2026-03-01T12:00:00Z",
        ],
        "accessionNumber": [
            "0000000001-26-000001",
            "0000000001-26-000002",
            "0000000001-26-000003",
        ],
        "primaryDocument": ["annual.htm", "amended.htm", "quarter.htm"],
    })
    as_of = datetime.fromisoformat("2026-03-01T20:00:00+08:00")

    filings = sec_provider.get_recent_filings("EXAMPLE", as_of)
    assert [filing.form for filing in filings] == ["10-Q", "10-K"]
    assert all(filing.accepted_at <= as_of for filing in filings)
    limited = sec_provider.get_recent_filings("EXAMPLE", as_of, limit=1)
    assert limited == filings[:1]


def test_as_of_before_acceptance_excludes_filing(recent):
    as_of = datetime.fromisoformat("2026-03-01T11:59:59+00:00")
    assert sec_provider.get_recent_filings("EXAMPLE", as_of) == []


def test_as_of_requires_timezone():
    with pytest.raises(ValueError, match="as_of 必须包含时区"):
        sec_provider.get_recent_filings("EXAMPLE", datetime(2026, 3, 1))


@pytest.mark.parametrize("kwargs", [{}, {"as_of": None}])
def test_optional_as_of_defaults_to_current_utc(recent, monkeypatch, kwargs):
    now = datetime.fromisoformat("2026-03-01T12:00:00+00:00")

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            return now

    monkeypatch.setattr(sec_provider, "datetime", FixedDatetime)
    assert len(sec_provider.get_recent_filings("EXAMPLE", **kwargs)) == 1
    recent["acceptanceDateTime"] = ["2026-03-01T12:00:01Z"]
    assert sec_provider.get_recent_filings("EXAMPLE", **kwargs) == []
