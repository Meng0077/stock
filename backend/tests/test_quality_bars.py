from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from stock_agent.market.fixtures import FIXTURE_BARS
from stock_agent.quality.bars import validate_bars
from stock_agent.quality.market_service import build_guarded_market_analysis


NEW_YORK = ZoneInfo("America/New_York")
AS_OF = datetime(2026, 9, 22, tzinfo=NEW_YORK)


def test_validate_bars_accepts_oldest_to_newest_order():
    result = validate_bars(
        bars=FIXTURE_BARS[("NVDA", "1d")],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
        allow_incomplete=True,
    )

    assert result.status == "degraded"
    assert all(issue.code != "bars_not_sorted" for issue in result.issues)


def test_validate_bars_checks_last_adjacent_pair():
    first, second, third = FIXTURE_BARS[("NVDA", "1d")]

    result = validate_bars(
        bars=[first, third, second],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
        allow_incomplete=True,
    )

    assert result.status == "rejected"
    assert result.issues[0].code == "bars_not_sorted"


def test_validate_bars_rejects_missing_bars():
    result = validate_bars(
        bars=[],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
    )

    assert result.status == "rejected"
    assert result.issues[0].code == "bars_missing"


def test_validate_bars_reports_insufficient_windows():
    result = validate_bars(
        bars=FIXTURE_BARS[("NVDA", "1d")][:2],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
    )

    assert result.status == "degraded"
    assert {issue.code for issue in result.issues} == {
        "bar_window_insufficient",
        "technical_windows_unavailable",
    }


def test_guarded_analysis_returns_partial_snapshot_for_short_window():
    analysis = build_guarded_market_analysis(
        symbol="NVDA",
        quote=None,
        bars=FIXTURE_BARS[("NVDA", "1d")][:2],
        as_of=AS_OF,
        market_state="unknown",
    )

    assert analysis.technical is not None
    assert analysis.technical.ma5 is None
    assert analysis.technical.latest_completed_close is not None
    assert analysis.quality.results[1].status == "degraded"


def test_validate_bars_rejects_future_bar():
    start_at = AS_OF + timedelta(days=1)
    bar = FIXTURE_BARS[("NVDA", "1d")][0].model_copy(
        update={
            "start_at": start_at,
            "end_at": start_at + timedelta(hours=6),
        }
    )

    result = validate_bars(
        bars=[bar],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
    )

    assert result.status == "rejected"
    assert result.issues[0].code == "bar_from_future"


@pytest.mark.parametrize(
    ("updates", "issue_code"),
    [
        ({"symbol": "TSLA"}, "bar_symbol_mismatch"),
        ({"timeframe": "1m"}, "bar_timeframe_mismatch"),
    ],
)
def test_validate_bars_rejects_identity_mismatch(
    updates,
    issue_code,
):
    bar = FIXTURE_BARS[("NVDA", "1d")][0].model_copy(
        update=updates
    )

    result = validate_bars(
        bars=[bar],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
    )

    assert result.status == "rejected"
    assert result.issues[0].code == issue_code


def test_validate_bars_rejects_mixed_adjustment():
    first, second = FIXTURE_BARS[("NVDA", "1d")][:2]
    second = second.model_copy(update={"adjustment": "raw"})

    result = validate_bars(
        bars=[first, second],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
    )

    assert result.status == "rejected"
    assert result.issues[0].code == "mixed_bar_adjustment"


def test_validate_bars_rejects_duplicate_interval():
    bar = FIXTURE_BARS[("NVDA", "1d")][0]

    result = validate_bars(
        bars=[bar, bar],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
    )

    assert result.status == "rejected"
    assert result.issues[0].code == "duplicate_bar"


def test_validate_bars_rejects_completed_bar_ending_after_as_of():
    bar = FIXTURE_BARS[("NVDA", "1d")][0].model_copy(
        update={
            "start_at": AS_OF - timedelta(hours=1),
            "end_at": AS_OF + timedelta(hours=1),
        }
    )

    result = validate_bars(
        bars=[bar],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
    )

    assert result.status == "rejected"
    assert result.issues[0].code == "completed_bar_from_future"


def test_validate_bars_rejects_multiple_incomplete_bars():
    first, second = FIXTURE_BARS[("NVDA", "1d")][:2]
    bars = [
        first.model_copy(update={"is_complete": False}),
        second.model_copy(update={"is_complete": False}),
    ]

    result = validate_bars(
        bars=bars,
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
        allow_incomplete=True,
    )

    assert result.status == "rejected"
    assert result.issues[0].code == "multiple_incomplete_bars"


def test_validate_bars_rejects_incomplete_bar_before_completed_bar():
    first, second = FIXTURE_BARS[("NVDA", "1d")][:2]
    first = first.model_copy(update={"is_complete": False})

    result = validate_bars(
        bars=[first, second],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
        allow_incomplete=True,
    )

    assert result.status == "rejected"
    assert result.issues[0].code == "incomplete_bar_not_last"


def test_validate_bars_rejects_incomplete_bar_when_not_allowed():
    bar = FIXTURE_BARS[("NVDA", "1d")][2]

    result = validate_bars(
        bars=[bar],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
    )

    assert result.status == "rejected"
    assert result.issues[0].code == "incomplete_bar_not_allowed"


def test_validate_bars_requires_at_least_one_completed_bar():
    bar = FIXTURE_BARS[("NVDA", "1d")][2]

    result = validate_bars(
        bars=[bar],
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
        allow_incomplete=True,
    )

    assert result.status == "rejected"
    assert result.issues[0].code == "completed_bars_missing"


def test_validate_bars_accepts_complete_sixty_bar_window():
    template = FIXTURE_BARS[("NVDA", "1d")][0]
    first_start = AS_OF - timedelta(days=90)
    bars = []
    for index in range(60):
        start_at = first_start + timedelta(days=index)
        end_at = start_at + timedelta(hours=6)
        bars.append(
            template.model_copy(
                update={
                    "start_at": start_at,
                    "end_at": end_at,
                    "updated_at": end_at,
                    "received_at": end_at + timedelta(seconds=1),
                }
            )
        )

    result = validate_bars(
        bars=bars,
        symbol="NVDA",
        timeframe="1d",
        as_of=AS_OF,
    )

    assert result.status == "usable"
    assert result.issues == []
