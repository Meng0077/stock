"""Day30 Step 2：真实 CPI 市场反应端到端验收。

使用 BLS 官方公布的 CPI 发布时间，
通过 Longbridge 获取 NVDA、QQQ、SOXL 的真实历史行情，
复用 Day28、Day29 的市场反应及相对收益计算。

只读行情，不调用模型，不提交交易订单。
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from stock_agent.macro.models.release import MacroReleaseEvent

from stock_agent.market.longbridge.config_factory import (
    build_longbridge_market_provider,
)

from stock_agent.market_reaction.multi_symbol import (
    MultiSymbolEventReaction,
    research_multi_symbol_event_reaction,
)

from stock_agent.market_reaction.comparison import (
    compare_event_symbols,
)


ROOT = Path(__file__).resolve().parents[1]

EASTERN = ZoneInfo("America/New_York")

SYMBOLS = ("NVDA", "QQQ", "SOXL")

WINDOWS = ("5m", "30m", "1h", "close")

# 官方公布的 CPI 发布时间：
# 2026-09-11 08:30 美东夏令时。
#
# 这是公告中的分钟级时间锚点，
# 不代表已经取得秒级实际发送时间。
RELEASE_AT = datetime(
    2026,
    9,
    11,
    8,
    30,
    tzinfo=EASTERN,
)

# 与 Step 1 使用相同的研究截止时间。
AS_OF = datetime(
    2026,
    9,
    14,
    12,
    0,
    tzinfo=EASTERN,
)


def build_release() -> MacroReleaseEvent:
    """构造用于本次真实联调的 CPI 发布事件。"""

    return MacroReleaseEvent(
        release_id="cpi:2026-09-11",
        release_type="cpi",
        release_date=date(2026, 9, 11),
        scheduled_release_at=RELEASE_AT,
        released_at=RELEASE_AT,
        release_date_source="bls",
        schedule_source="bls",
        period_binding="verified",

        # 当前步骤只验证发布时间与真实市场行情。
        # Actual、Consensus 暂时不在本次测试范围内。
        metrics=[],
    )


def format_pct(value: Decimal | None) -> str:
    """将 Decimal 收益率转换为易读的百分比。"""

    if value is None:
        return "-"

    return f"{value:+.3f}%"


def print_market_reactions(
    event: MultiSymbolEventReaction,
) -> bool:
    """打印所有证券、所有观察窗口的计算结果。

    返回：
        True：全部观察窗口均为 usable。
        False：存在缺失、待完成或不可计算的观察窗口。
    """

    print("\n========== Market Reaction ==========")

    print("release_id=", event.release_id)
    print("event_at=", event.event_at)

    all_usable = True

    for symbol in event.symbols:
        reaction = event.reactions[symbol]

        print(f"\n---------- {symbol} ----------")

        print(
            "reference_price=",
            reaction.reference_price,
        )

        print(
            "reference_at=",
            reaction.reference_at,
        )

        print(
            "issues=",
            reaction.issues,
        )

        if reaction.reference_price is None:
            all_usable = False

        for window in WINDOWS:
            observation = reaction.observations.get(window)

            if observation is None:
                print(
                    window,
                    "status=not_returned",
                )
                all_usable = False
                continue

            print(
                window,
                "status=", observation.status,
                "price=", observation.price,
                "price_at=", observation.price_at,
                "return=", format_pct(
                    observation.return_pct
                ),
                "reason=", observation.reason,
            )

            if observation.status != "usable":
                all_usable = False

            # 防止上游错误地将没有收益率的结果
            # 标记为 usable。
            if (
                observation.status == "usable"
                and observation.return_pct is None
            ):
                raise AssertionError(
                    f"{symbol} {window}: "
                    "usable but return_pct is None"
                )

    return all_usable


def print_comparison(
    event: MultiSymbolEventReaction,
    *,
    lhs: str,
    rhs: str,
) -> None:
    """复用 Day29 的可选相对收益比较。"""

    comparison = compare_event_symbols(
        event=event,
        lhs_symbol=lhs,
        rhs_symbol=rhs,
    )

    print(
        f"\n========== {lhs} - {rhs} =========="
    )

    for window in WINDOWS:
        observation = comparison.observations[window]

        difference = observation.difference_pp

        difference_text = (
            f"{difference:+.3f} pp"
            if difference is not None
            else "-"
        )

        print(
            window,
            "lhs=", format_pct(
                observation.lhs_return_pct
            ),
            "rhs=", format_pct(
                observation.rhs_return_pct
            ),
            "difference=", difference_text,
            "status=", observation.status,
        )

    print(
        "comparison_issues=",
        comparison.issues,
    )


def main() -> None:
    """执行真实 CPI 市场反应联调。"""

    # 1. 加载已有长桥配置。
    load_dotenv(
        ROOT / "backend" / ".env",
        override=False,
    )

    provider = build_longbridge_market_provider()

    # 2. 构造真实宏观发布事件。
    release = build_release()

    print("source= BLS + Longbridge")
    print("release_id=", release.release_id)
    print("official_public_at=", RELEASE_AT)
    print("as_of=", AS_OF)
    print("symbols=", SYMBOLS)

    # 3. 调用 Day29 多证券研究入口。
    #
    # 内部依次调用 Day28 research_event_reaction，
    # 自动完成分钟行情查询、时间对齐、收益率计算
    # 和正式收盘日线查询。
    event = research_multi_symbol_event_reaction(
        release=release,
        symbols=SYMBOLS,
        provider=provider,
        as_of=AS_OF,
    )

    # 4. 验证 Day27 是否正确统一为 UTC。
    expected_event_at = RELEASE_AT.astimezone(
        timezone.utc
    )

    assert event.event_at == expected_event_at, (
        f"Unexpected event_at: {event.event_at}"
    )

    assert event.symbols == SYMBOLS

    # 5. 输出三只证券在四个窗口的市场反应。
    all_usable = print_market_reactions(event)

    # 6. 复用 Day29 比较层，不重新查询行情。
    print_comparison(
        event,
        lhs="NVDA",
        rhs="QQQ",
    )

    print_comparison(
        event,
        lhs="SOXL",
        rhs="QQQ",
    )

    # 7. 严格验收。
    #
    # 即使部分行情不可用，也先打印全部结果，
    # 最后再确定是否通过。
    if not all_usable:
        raise SystemExit(
            "\nDay30 verification incomplete: "
            "some observations are not usable."
        )

    print(
        "\nDay30 real market reaction "
        "verification passed."
    )


if __name__ == "__main__":
    main()