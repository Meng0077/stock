from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from stock_agent.market.schemas import (
    Bar,
    Quote,
)


from stock_agent.market.fixture_provider import (
    FixtureMarketDataProvider,
)


NEW_YORK = ZoneInfo(
    "America/New_York"
)


FIXTURE_QUOTES = {
    "NVDA": Quote(
        symbol="NVDA",
        price=Decimal("200.00"),
        currency="USD",
        quoted_at=datetime(2026,9,21,16,0,tzinfo=NEW_YORK,),
        received_at=datetime(2026,9,21,16,0,1,tzinfo=NEW_YORK,),
        session="closed",
        data_mode="fixture",
        is_delayed=False,
        source="local_fixture",
    ),

    "AMD": Quote(
        symbol="AMD",
        price=Decimal("150.00"),
        currency="USD",
        quoted_at=datetime(2026,9,21,16,0,tzinfo=NEW_YORK,),
        received_at=datetime(2026,9,21,16,0,1,tzinfo=NEW_YORK,),
        session="closed",
        data_mode="fixture",
        is_delayed=False,
        source="local_fixture",
    ),
}


FIXTURE_BARS = {
    (
        "NVDA",
        "1d",
    ): [
        Bar(
            symbol="NVDA",
            timeframe="1d",
            start_at=datetime( 2026, 9, 17, 9, 30, tzinfo=NEW_YORK,),
            end_at=datetime( 2026, 9, 17, 16, 0, tzinfo=NEW_YORK,),
            open=Decimal("198"),
            high=Decimal("203"),
            low=Decimal("197"),
            close=Decimal("202"),
            volume=180_000_000,
            is_complete=True,
            adjustment="split_adjusted",
            source="local_fixture",
            data_mode="fixture",
            updated_at=datetime( 2026, 9, 17, 16, 0, tzinfo=NEW_YORK),
            received_at=datetime(2026, 9, 17, 16, 0, 1, tzinfo=NEW_YORK),
        ),
        Bar(
            symbol="NVDA",
            timeframe="1d",
            start_at=datetime( 2026, 9, 18, 9, 30, tzinfo=NEW_YORK,),
            end_at=datetime( 2026, 9, 18, 16, 0, tzinfo=NEW_YORK,),
            updated_at=datetime( 2026, 9, 18, 16, 0, tzinfo=NEW_YORK,),
            open=Decimal("202"),
            high=Decimal("205"),
            low=Decimal("199"),
            close=Decimal("201"),
            volume=170_000_000,
            is_complete=True,
            adjustment="split_adjusted",
            source="local_fixture",
            data_mode="fixture",
            received_at=datetime(2026, 9, 18, 16, 0, 1, tzinfo=NEW_YORK),
        ),
        Bar(
            symbol="NVDA",
            timeframe="1d",

            # 今天的日 K 从 09:30 开始。
            start_at=datetime(
                2026,
                9,
                21,
                9,
                30,
                tzinfo=NEW_YORK,
            ),

            # 理论结束时间仍然是 16:00。
            end_at=datetime(
                2026,
                9,
                21,
                16,
                0,
                tzinfo=NEW_YORK,
            ),

            # 但当前这份快照只更新到了 14:30。
            updated_at=datetime(
                2026,
                9,
                21,
                14,
                30,
                tzinfo=NEW_YORK,
            ),

            open=Decimal("201"),
            high=Decimal("207"),
            low=Decimal("200"),
            close=Decimal("206"),

            volume=120_000_000,

            # 这根日 K 还没有走完。
            is_complete=False,

            adjustment="split_adjusted",
            source="local_fixture",
            data_mode="fixture",
            received_at=datetime(2026, 9, 21, 14, 30, 1, tzinfo=NEW_YORK),
        ),
    ],
}


FIXTURE_MARKET_PROVIDER = FixtureMarketDataProvider(
    quotes=FIXTURE_QUOTES,
    bars=FIXTURE_BARS,
)
