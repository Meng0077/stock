from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from stock_agent.market.fixtures import FIXTURE_BARS
from stock_agent.quality.bars import validate_bars


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
