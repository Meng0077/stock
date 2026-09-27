from datetime import datetime
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
