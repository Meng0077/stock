from datetime import datetime

from stock_agent.decision.models import (
    ContextComponent,
    MarketContext,
)
from stock_agent.macro.models.snapshot import (
    MacroSnapshot,
)
from stock_agent.market.schemas import Quote
from stock_agent.market.technical import (
    MarketTechnicalSnapshot,
)
from stock_agent.market_reaction.models import (
    MarketReactionResult,
)
from stock_agent.quality.report import (
    DataQualityReport,
)


def _validate_quote_technical_consistency(
    *,
    quote: Quote | None,
    technical: MarketTechnicalSnapshot | None,
) -> None:
    """检查声明使用 Quote 的 Technical 是否与 Quote 一致。"""
    if technical is None:
        return

    # Technical 没有使用 Quote 作为当前价格来源，
    # 不需要和当前 Quote 做价格一致性检查。
    if technical.price_source != 'quote':
        return

    # Technical 明确声明价格来自 Quote，
    # 那么对应 Quote 必须存在。
    if quote is None:
        raise ValueError("technical price_source is quote but quote is missing")

    if quote.price != technical.current_price:
        raise ValueError("technical current_price does not match quote price")

    if quote.quoted_at != technical.price_at:
        raise ValueError("technical price_at does not match quote quoted_at")

def _validate_macro_temporal_consistency(
    *,
    macro: MacroSnapshot | None,
) -> None:
    """检查 MacroSnapshot 内部是否存在未来发布数据。"""
    if macro is None:
        return

    # MacroSnapshot 目前的模型字段还是普通 datetime，
    # 所以在进入 MarketContext 前明确要求时区。
    if (
        macro.as_of.tzinfo is None
        or macro.as_of.utcoffset() is None
    ):
        raise ValueError(
            "macro as_of must be timezone-aware"
        )

    for release in macro.recent_releases:
        if release.released_at is None:
            continue

        if (
            release.released_at.tzinfo is None
            or release.released_at.utcoffset() is None
        ):
            raise ValueError(
                "macro released_at must be timezone-aware"
            )

        if release.released_at > macro.as_of:
            raise ValueError("macro release is after macro as_of")

def _validate_market_reaction_temporal_consistency(
    *,
    market_reaction: MarketReactionResult | None,
    as_of: datetime,
) -> None:
    """检查 MarketReaction 内部的时间关系。

    target_at 是观察计划时间，可以晚于 as_of；
    price_at 是实际使用的数据时间，不能越过 target_at。

    已标记为 usable 的观察窗口必须已经到达。
    """
    if market_reaction is None:
        return
    event_at = market_reaction.event_at
    reference_at = market_reaction.reference_at

    # 没有可用事件时间时，
    # MarketReaction 可能只是一个结构化 unavailable 结果。
    #
    # 此时没有必要继续检查 reference 相对 event 的关系。

    if event_at is not None and reference_at is not None:
        if reference_at > event_at:
            raise ValueError(
                "market reaction reference_at "
                "is after event_at"
            )

    for window, observation in market_reaction.observations.items():
        # target_at 是计划观察时刻。
        #
        # pending 的未来 target 是合法的，
        # usable 的未来 target 则不合法。
        if observation.status == 'usable' and observation.target_at > as_of:
            raise ValueError(f"usable market reaction observation {window} target_at is after as_of")

        # price_at 表示真正使用的数据时间。
        # 不能使用目标观察时刻之后的行情。
        if observation.price_at and observation.price_at > observation.target_at:
            raise ValueError("market reaction observation {window} price_at is after target_at")


def build_market_context(
    *,
    symbol: str,
    as_of: datetime,
    requested_components: set[ContextComponent],
    quote: Quote | None = None,
    technical: MarketTechnicalSnapshot | None = None,
    macro: MacroSnapshot | None = None,
    market_reaction: MarketReactionResult | None = None,
    quality_report: DataQualityReport | None = None,
) -> MarketContext:
    """把已经准备好的研究数据组装成统一 MarketContext。

    这里只负责组装。

    不负责：
        - 请求行情；
        - 计算技术指标；
        - 获取宏观数据；
        - 计算 Market Reaction；
        - 判断趋势。
    """

    # Quote + Technical 同一价格快照
    _validate_quote_technical_consistency(
        quote=quote,
        technical=technical
    )
    # MacroSnapshot ↔ Release 未来宏观数据
    _validate_macro_temporal_consistency(macro=macro)

    # MarketReaction 时间关系 look-ahead
    _validate_market_reaction_temporal_consistency(
        market_reaction=market_reaction,
        as_of=as_of
    )

    return MarketContext(
        symbol=symbol,
        as_of=as_of,
        requested_components=requested_components,
        quote=quote,
        technical=technical,
        macro=macro,
        market_reaction=market_reaction,
        quality_report=quality_report,
    )
