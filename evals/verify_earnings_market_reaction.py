"""NVDA 最近财报的 SEC + Longbridge 真实端到端验收。

只读 SEC filing 和 Longbridge 历史行情，
不调用模型，不提交交易订单。

运行：
PYTHONPATH=backend/src backend/.venv/bin/python \
    evals/verify_earnings_market_reaction.py
"""

from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from stock_agent.market.earnings import (
    get_latest_earnings_release,
    research_earnings_reaction,
)
from stock_agent.market.longbridge.config_factory import (
    build_longbridge_market_provider,
)


ROOT = Path(__file__).resolve().parents[1]
SYMBOL = "NVDA"
WINDOWS = ("5m", "30m", "1h", "close")


def main() -> None:
    """执行最近一次 NVDA 财报的真实市场反应联调。"""
    load_dotenv(
        ROOT / "backend" / ".env",
        override=False,
    )

    as_of = datetime.now(timezone.utc)

    # 1. 通过 SEC 找到 as_of 前最近一次 Item 2.02 8-K。
    earnings = get_latest_earnings_release(
        symbol=SYMBOL,
        as_of=as_of,
    )

    assert earnings is not None, (
        "SEC did not return an NVDA earnings 8-K before as_of"
    )
    assert earnings.symbol == SYMBOL
    assert earnings.released_at <= as_of
    assert earnings.released_at_source == "sec_8k_accepted_at"
    assert earnings.event_id == (
        f"earnings:{SYMBOL}:{earnings.accession_number}"
    )
    assert earnings.source_url.startswith(
        "https://www.sec.gov/Archives/edgar/data/"
    )

    print("source= SEC + Longbridge")
    print("symbol=", earnings.symbol)
    print("event_id=", earnings.event_id)
    print("report_date=", earnings.report_date)
    print("sec_accepted_at=", earnings.released_at)
    print("source_url=", earnings.source_url)
    print("as_of=", as_of)

    # 2. 使用真实 Longbridge 历史分钟线和日线计算反应。
    provider = build_longbridge_market_provider()
    reaction = research_earnings_reaction(
        earnings=earnings,
        symbol=SYMBOL,
        provider=provider,
        as_of=as_of,
    )

    assert reaction.release_id == earnings.event_id
    assert reaction.release_type == "earnings"
    assert reaction.symbol == SYMBOL
    assert reaction.event_at == earnings.released_at
    assert reaction.event_time_source == "sec_8k_accepted_at"
    assert reaction.reference_price is not None
    assert reaction.reference_price > 0
    assert reaction.reference_at is not None
    assert reaction.reference_at <= earnings.released_at
    assert reaction.reference_source == "longbridge"
    assert set(reaction.observations) == set(WINDOWS)

    print("reference_price=", reaction.reference_price)
    print("reference_at=", reaction.reference_at)
    print("issues=", reaction.issues)

    # 3. 最近财报已经结束，四个观察窗口都必须可计算。
    for window in WINDOWS:
        observation = reaction.observations[window]

        print(
            window,
            "status=", observation.status,
            "price=", observation.price,
            "price_at=", observation.price_at,
            "return_pct=", observation.return_pct,
            "source=", observation.price_source,
        )

        assert observation.status == "usable", (
            f"{window} is not usable: {observation.reason}"
        )
        assert observation.price is not None
        assert observation.price > 0
        assert observation.price_at is not None
        assert observation.price_at <= as_of
        assert observation.return_pct is not None
        assert observation.price_source == "longbridge"

    print("NVDA earnings market reaction verification passed.")


if __name__ == "__main__":
    main()
