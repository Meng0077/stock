from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from stock_agent.market.schemas import Quote
from stock_agent.quality.market_service import build_guarded_market_analysis
from stock_agent.quality.quote import validate_quote


AS_OF = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


def make_quote(
    *,
    age_seconds: int,
    is_delayed: bool | None = None,
) -> Quote:
    quoted_at = AS_OF - timedelta(seconds=age_seconds)
    return Quote(
        symbol="NVDA",
        price=Decimal("187.25"),
        currency="USD",
        quoted_at=quoted_at,
        received_at=quoted_at + timedelta(seconds=1),
        session="regular",
        data_mode="live",
        is_delayed=is_delayed,
        source="longbridge",
    )


def test_unknown_market_state_keeps_fresh_quote_with_warning():
    result = validate_quote(
        quote=make_quote(age_seconds=30),
        symbol="NVDA",
        as_of=AS_OF,
        market_state="unknown",
    )

    assert result.status == "degraded"
    assert [issue.code for issue in result.issues] == [
        "market_state_unknown",
        "quote_delay_unknown",
    ]


def test_unknown_market_state_rejects_stale_quote():
    result = validate_quote(
        quote=make_quote(age_seconds=61),
        symbol="NVDA",
        as_of=AS_OF,
        market_state="unknown",
    )

    assert result.status == "rejected"
    assert [issue.code for issue in result.issues] == ["quote_stale"]


def test_missing_quote_is_rejected():
    result = validate_quote(
        quote=None,
        symbol="NVDA",
        as_of=AS_OF,
        market_state="unknown",
    )

    assert result.status == "rejected"
    assert [issue.code for issue in result.issues] == ["quote_missing"]


def test_future_quote_is_rejected():
    result = validate_quote(
        quote=make_quote(age_seconds=-1),
        symbol="NVDA",
        as_of=AS_OF,
        market_state="trading",
    )

    assert result.status == "rejected"
    assert [issue.code for issue in result.issues] == ["quote_after_as_of"]


def test_delayed_quote_is_degraded():
    result = validate_quote(
        quote=make_quote(age_seconds=30, is_delayed=True),
        symbol="NVDA",
        as_of=AS_OF,
        market_state="trading",
    )

    assert result.status == "degraded"
    assert [issue.code for issue in result.issues] == ["quote_delayed"]


@pytest.mark.parametrize(
    ("updates", "issue_code"),
    [
        ({"symbol": "TSLA"}, "symbol_mismatch"),
        (
            {
                "received_at": AS_OF - timedelta(seconds=31),
            },
            "quote_after_received_at",
        ),
        ({"data_mode": "fixture"}, "fixture_not_current_price"),
    ],
)
def test_invalid_quote_identity_or_provenance_is_rejected(
    updates,
    issue_code,
):
    quote = make_quote(age_seconds=30).model_copy(
        update=updates
    )

    result = validate_quote(
        quote=quote,
        symbol="NVDA",
        as_of=AS_OF,
        market_state="trading",
    )

    assert result.status == "rejected"
    assert [issue.code for issue in result.issues] == [issue_code]


def test_unknown_market_state_preserves_delay_warning():
    result = validate_quote(
        quote=make_quote(age_seconds=30, is_delayed=True),
        symbol="NVDA",
        as_of=AS_OF,
        market_state="unknown",
    )

    assert result.status == "degraded"
    assert [issue.code for issue in result.issues] == [
        "market_state_unknown",
        "quote_delayed",
    ]


def test_closed_market_preserves_quote_limitations():
    quote = make_quote(age_seconds=3600).model_copy(
        update={"data_mode": "historical"}
    )

    result = validate_quote(
        quote=quote,
        symbol="NVDA",
        as_of=AS_OF,
        market_state="closed",
    )

    assert result.status == "degraded"
    assert [issue.code for issue in result.issues] == [
        "market_closed",
        "quote_not_live",
        "quote_delay_unknown",
    ]


def test_fresh_confirmed_live_quote_is_usable():
    result = validate_quote(
        quote=make_quote(age_seconds=30, is_delayed=False),
        symbol="NVDA",
        as_of=AS_OF,
        market_state="trading",
    )

    assert result.status == "usable"
    assert result.issues == []


def test_guarded_market_analysis_keeps_degraded_quote_for_display():
    quote = make_quote(age_seconds=30)

    analysis = build_guarded_market_analysis(
        symbol="NVDA",
        quote=quote,
        bars=[],
        as_of=AS_OF,
        market_state="unknown",
    )

    assert analysis.current_quote is quote
    assert analysis.technical is None
    assert analysis.quality.results[0].status == "degraded"
    assert analysis.quality.results[1].status == "rejected"
