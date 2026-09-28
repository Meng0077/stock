from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.market.errors import MarketDataCapabilityError
from stock_agent.market.intraday import IntradayBar
from stock_agent.market_reaction.alignment import (
    align_event_with_bars,
    assess_event_alignment,
    fetch_event_intraday_bars,
    prepare_event_market_data,
)
from stock_agent.market_reaction.event_time import resolve_event_time
from stock_agent.market_reaction.service import research_event_reaction


EASTERN = ZoneInfo("America/New_York")


class RecordingProvider:
    def __init__(self, bars: list[IntradayBar]) -> None:
        self.bars = bars
        self.calls: list[tuple[str, dict]] = []

    def get_intraday_bars(self, symbol: str, **kwargs) -> list[IntradayBar]:
        self.calls.append((symbol, kwargs))
        return self.bars


class CapabilityUnavailableProvider:
    def get_intraday_bars(self, symbol: str, **kwargs) -> list[IntradayBar]:
        raise MarketDataCapabilityError("minute bars unavailable")


def make_release(
    *,
    release_date: date = date(2026, 9, 25),
    scheduled_release_at: datetime | None = None,
    released_at: datetime | None = None,
) -> MacroReleaseEvent:
    return MacroReleaseEvent(
        release_id=f"cpi:{release_date.isoformat()}",
        release_type="cpi",
        release_date=release_date,
        scheduled_release_at=scheduled_release_at,
        released_at=released_at,
        release_date_source="fixture",
        schedule_source="fixture" if scheduled_release_at else None,
        period_binding="verified",
        metrics=[],
    )


def make_bar(start_at: datetime) -> IntradayBar:
    end_at = start_at + timedelta(minutes=1)
    return IntradayBar(
        symbol="NVDA",
        start_at=start_at,
        end_at=end_at,
        open=Decimal("180"),
        high=Decimal("181"),
        low=Decimal("179"),
        close=Decimal("180.5"),
        volume=100,
        is_complete=True,
        adjustment="raw",
        updated_at=end_at,
        received_at=end_at,
        source="fixture",
        data_mode="fixture",
        session="pre",
    )


def test_align_event_at_minute_boundary() -> None:
    event_at = datetime(2026, 9, 25, 12, 30, tzinfo=timezone.utc)
    pre_bar = make_bar(event_at - timedelta(minutes=1))
    post_bar = make_bar(event_at)

    pre_bars, post_bars, crossing_bar = align_event_with_bars(
        event_at=event_at,
        bars=[pre_bar, post_bar],
    )

    assert pre_bars == [pre_bar]
    assert post_bars == [post_bar]
    assert crossing_bar is None


def test_resolve_event_time_does_not_infer_scheduled_time() -> None:
    scheduled_at = datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN)

    resolution = resolve_event_time(
        make_release(scheduled_release_at=scheduled_at),
        as_of=datetime(2026, 9, 25, 9, 0, tzinfo=EASTERN),
    )

    assert resolution.event_at is None
    assert resolution.reason == "actual_release_time_missing"


@pytest.mark.parametrize(
    ("release_date", "released_at", "as_of", "reason"),
    [
        (
            date(2026, 9, 25),
            datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN),
            datetime(2026, 9, 25, 8, 29, tzinfo=EASTERN),
            "release_not_yet_published",
        ),
        (
            date(2026, 9, 24),
            datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN),
            datetime(2026, 9, 25, 9, 0, tzinfo=EASTERN),
            "release_date_time_conflict",
        ),
    ],
)
def test_resolve_event_time_rejects_invalid_actual_time(
    release_date: date,
    released_at: datetime,
    as_of: datetime,
    reason: str,
) -> None:
    resolution = resolve_event_time(
        make_release(
            release_date=release_date,
            released_at=released_at,
        ),
        as_of=as_of,
    )

    assert resolution.event_at is None
    assert resolution.reason == reason


def test_resolve_event_time_normalizes_actual_time_to_utc() -> None:
    released_at = datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN)

    resolution = resolve_event_time(
        make_release(released_at=released_at),
        as_of=datetime(2026, 9, 25, 9, 0, tzinfo=EASTERN),
    )

    assert resolution.event_at == datetime(
        2026,
        9,
        25,
        12,
        30,
        tzinfo=timezone.utc,
    )
    assert resolution.reason is None


def test_fetch_uses_utc_window_and_as_of_cutoff() -> None:
    event_at = datetime(2026, 9, 25, 8, 30, 30, tzinfo=EASTERN)
    as_of = datetime(2026, 9, 25, 9, 0, tzinfo=EASTERN)
    provider = RecordingProvider([])

    request, bars = fetch_event_intraday_bars(
        event_at=event_at,
        symbol="NVDA",
        provider=provider,
        as_of=as_of,
    )

    assert request.start_at == datetime(
        2026,
        9,
        25,
        12,
        25,
        tzinfo=timezone.utc,
    )
    assert request.end_at == as_of.astimezone(timezone.utc)
    assert bars == []
    assert provider.calls == [
        (
            "NVDA",
            {
                "start_at": request.start_at,
                "end_at": request.end_at,
                "as_of": request.as_of,
            },
        )
    ]


def test_align_event_inside_minute_identifies_crossing_bar() -> None:
    minute_start = datetime(2026, 9, 25, 12, 30, tzinfo=timezone.utc)
    crossing = make_bar(minute_start)

    pre_bars, post_bars, crossing_bar = align_event_with_bars(
        event_at=minute_start + timedelta(seconds=30),
        bars=[crossing],
    )

    assert pre_bars == []
    assert post_bars == []
    assert crossing_bar == crossing


def test_assess_event_alignment_is_ready_with_nearby_bars() -> None:
    event_at = datetime(2026, 9, 25, 12, 30, tzinfo=timezone.utc)
    pre_bar = make_bar(event_at - timedelta(minutes=1))
    post_bar = make_bar(event_at)

    status, issues = assess_event_alignment(
        event_at=event_at,
        as_of=event_at + timedelta(minutes=2),
        pre_bars=[pre_bar],
        post_bars=[post_bar],
        crossing_bar=None,
    )

    assert status == "ready"
    assert issues == []


def test_assess_event_alignment_waits_for_post_bar() -> None:
    event_at = datetime(2026, 9, 25, 12, 30, tzinfo=timezone.utc)
    pre_bar = make_bar(event_at - timedelta(minutes=1))

    status, issues = assess_event_alignment(
        event_at=event_at,
        as_of=event_at + timedelta(seconds=30),
        pre_bars=[pre_bar],
        post_bars=[],
        crossing_bar=None,
    )

    assert status == "incomplete"
    assert issues == ["post_bar_not_yet_complete"]


def test_assess_marks_completed_but_absent_post_bar_as_missing() -> None:
    event_at = datetime(2026, 9, 25, 12, 30, tzinfo=timezone.utc)
    pre_bar = make_bar(event_at - timedelta(minutes=1))

    status, issues = assess_event_alignment(
        event_at=event_at,
        as_of=event_at + timedelta(minutes=1),
        pre_bars=[pre_bar],
        post_bars=[],
        crossing_bar=None,
    )

    assert status == "incomplete"
    assert issues == ["post_bar_missing"]


def test_assess_is_ready_with_warning_when_event_minute_is_missing() -> None:
    minute_start = datetime(2026, 9, 25, 12, 30, tzinfo=timezone.utc)
    event_at = minute_start + timedelta(seconds=20)
    pre_bar = make_bar(minute_start - timedelta(minutes=1))
    post_bar = make_bar(minute_start + timedelta(minutes=1))

    status, issues = assess_event_alignment(
        event_at=event_at,
        as_of=minute_start + timedelta(minutes=3),
        pre_bars=[pre_bar],
        post_bars=[post_bar],
        crossing_bar=None,
    )

    assert status == "ready"
    assert issues == ["event_minute_not_observed"]


def test_prepare_stops_before_provider_when_actual_time_is_missing() -> None:
    provider = RecordingProvider([])
    release = make_release(
        scheduled_release_at=datetime(
            2026,
            9,
            25,
            8,
            30,
            tzinfo=EASTERN,
        )
    )

    result = prepare_event_market_data(
        release=release,
        symbol="nvda",
        provider=provider,
        as_of=datetime(2026, 9, 25, 9, 0, tzinfo=EASTERN),
    )

    assert result.status == "unavailable"
    assert result.issues == ["actual_release_time_missing"]
    assert result.event_at is None
    assert provider.calls == []


def test_prepare_associates_release_symbol_and_aligned_bars() -> None:
    released_at = datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN)
    pre_bar = make_bar(released_at - timedelta(minutes=1))
    post_bar = make_bar(released_at)
    provider = RecordingProvider([pre_bar, post_bar])

    result = prepare_event_market_data(
        release=make_release(released_at=released_at),
        symbol=" nvda ",
        provider=provider,
        as_of=released_at + timedelta(minutes=2),
    )

    assert result.release_id == "cpi:2026-09-25"
    assert result.release_type == "cpi"
    assert result.symbol == "NVDA"
    assert result.event_at == released_at.astimezone(timezone.utc)
    assert result.pre_bars == [pre_bar]
    assert result.post_bars == [post_bar]
    assert result.crossing_bar is None
    assert result.status == "ready"
    assert result.issues == []
    assert len(provider.calls) == 1


def test_prepare_leaves_capability_error_for_day28() -> None:
    released_at = datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN)

    with pytest.raises(MarketDataCapabilityError):
        prepare_event_market_data(
            release=make_release(released_at=released_at),
            symbol="NVDA",
            provider=CapabilityUnavailableProvider(),
            as_of=released_at + timedelta(minutes=2),
        )


def test_service_converts_minute_capability_error_to_result() -> None:
    released_at = datetime(2026, 9, 25, 8, 30, tzinfo=EASTERN)

    result = research_event_reaction(
        release=make_release(released_at=released_at),
        symbol=" nvda ",
        provider=CapabilityUnavailableProvider(),
        as_of=released_at + timedelta(minutes=2),
    )

    assert result.release_id == "cpi:2026-09-25"
    assert result.symbol == "NVDA"
    assert result.event_at == released_at.astimezone(timezone.utc)
    assert result.reference_price is None
    assert result.observations == {}
    assert result.issues == ["minute_data_capability_unavailable"]
