from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
)

from stock_agent.market.indicators import (
    calculate_atr,
    calculate_ma,
    calculate_return,
)
from stock_agent.market.price_structure import (
    PriceStructureSnapshot,
    build_price_structure_snapshot,
)
from stock_agent.market.schemas import Bar, Quote
from stock_agent.market.volume import VolumeFeatures, build_volume_features

TECHNICAL_CALCULATION_VERSION: Literal["technical-v1"] = "technical-v1"

class TechnicalInputs(BaseModel):
    """经过校验和分类的技术分析输入。

    completed_bars:
        按时间从旧到新排列的已完成日 K。

    current_bar:
        当前正在形成的日 K；不存在时为 None。

    quote:
        当前研究时点可用的行情报价；不存在时为 None。
    """

    model_config = ConfigDict(extra="forbid")

    completed_bars: list[Bar]
    current_bar: Bar | None
    quote: Quote | None

def prepare_technical_inputs(
    *,
    quote: Quote | None,
    bars: list[Bar],
    is_live_query: bool,
) -> TechnicalInputs:
    """校验并整理技术指标计算所需的行情。

    Args:
        quote:
            Provider 返回的可选报价。

        bars:
            Provider 返回的日 K，可以包含当前 incomplete Bar。

        is_live_query:
            是否为实时行情分析。
            历史分析不使用 incomplete Bar。

    Returns:
        分类后的 completed_bars、current_bar 和 quote。

    不负责：
        - 获取行情；
        - 判定报价是否过期；
        - 计算技术指标；
        - 生成交易信号。
    """

    current_bar = None
    if is_live_query and bars and not bars[-1].is_complete:
        current_bar = bars[-1]

    return TechnicalInputs(
        completed_bars=[bar for bar in bars if bar.is_complete],
        current_bar=current_bar,
        quote=quote,
    )

class CurrentBarStructure(BaseModel):
    """当前正在形成的 Daily Bar 的确定性盘中特征。

    只描述当前交易日已经发生的价格结构，
    不负责趋势判断、预测和交易信号。
    """

    model_config = ConfigDict(
        extra="forbid"
    )

    # 当前 Daily Bar 自身的 OHLC。
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    # 可能来自 Quote.price， 因此不一定严格等于 current_bar.close。
    current_price: Decimal

    change_from_previous_close_pct: Decimal | None

    # 当前交易日 high-low 的价格跨度，
    # 相对于今日 open 的百分比。
    intraday_range_pct: Decimal

    # 当前价格位于今日 low-high 区间中的位置。
    #
    # 0   = 当前位于今日 low
    # 50  = 当前位于区间中点
    # 100 = 当前位于今日 high
    #
    # 如果 high == low，则无法定义，返回 None。
    range_position_pct: Decimal | None

    # 当前价格距离今日 high 已经回撤多少。
    pullback_from_high_pct: Decimal

    # 当前价格相比今日 low 已经反弹多少。
    rebound_from_low_pct: Decimal

HUNDRED = Decimal("100")

def calculate_current_bar_structure(
    *,
    current_bar: Bar,
    current_price: Decimal,
    previous_close: Decimal | None,
) -> CurrentBarStructure:
    """计算当前 incomplete Daily Bar 的盘中结构。"""
    effective_high = max(current_price, current_bar.high)
    effective_low = min(current_price, current_bar.low)

    change_from_previous_close_pct = None
    if previous_close is not None:
        change_from_previous_close_pct =( (current_price / previous_close) - 1) * HUNDRED

    intraday_range_pct = ((effective_high - effective_low) / current_bar.open) * HUNDRED

    if effective_high == effective_low:
        range_position_pct = None
    else:
        range_position_pct =( (current_price - effective_low) / (effective_high - effective_low)) * HUNDRED

    pullback_from_high_pct = ( - current_price + effective_high) / effective_high * HUNDRED

    rebound_from_low_pct = (current_price - effective_low) / effective_low * HUNDRED

    return CurrentBarStructure(
        open=current_bar.open,
        high=effective_high,
        low=effective_low,
        current_price=current_price,
        change_from_previous_close_pct=change_from_previous_close_pct,
        intraday_range_pct=intraday_range_pct,
        range_position_pct=range_position_pct,
        pullback_from_high_pct=pullback_from_high_pct,
        rebound_from_low_pct=rebound_from_low_pct,
        close=current_bar.close,
    )


class MarketTechnicalSnapshot(BaseModel):
    "某一时刻的确定性市场技术特征快照。"

    model_config = ConfigDict(
        extra="forbid"
    )

    symbol: str
    calculation_version: Literal["technical-v1"]

    # 当前用于分析的市场价格。
    current_price: Decimal | None

    price_source: Literal[
        "quote",
        "incomplete_bar",
        "completed_close",
    ] | None

    # 当前参考价格对应的市场时间。
    price_at: datetime | None

    # 最近一个完成交易日的收盘价。
    latest_completed_close: Decimal | None

    # ---------- Trend ----------
    ma5: Decimal | None
    ma20: Decimal | None
    ma50: Decimal | None

    # ---------- Momentum ----------
    return_5d_pct: Decimal | None
    return_20d_pct: Decimal | None

    # ---------- Volatility ----------
    atr14: Decimal | None

    # ---------- Historical Price Structure ----------
    price_structure: PriceStructureSnapshot

    # ---------- Current Intraday Structure ----------
    current_bar_structure: CurrentBarStructure | None

    # ---------- Volume ----------
    volume_features: VolumeFeatures

    # # 当前是否存在正在形成中的 Bar。
    # has_incomplete_bar: bool

def resolve_current_price(
    *,
    quote: Quote | None,
    current_bar: Bar | None,
    completed_bars: list[Bar],
) -> tuple[
    Decimal | None,
    Literal[
        "quote",
        "incomplete_bar",
        "completed_close",
    ] | None,
    datetime | None,
]:
    """选择 Technical Snapshot 使用的当前参考价格。

    优先级：
        Quote
        -> incomplete Bar close
        -> latest completed Bar close

    Returns:
        (price, source, price_at)

        没有任何价格数据时：
        (None, None, None)
    """

    if quote is not None:
        return quote.price, "quote", quote.quoted_at

    if current_bar is not None:
        return (
            current_bar.close,
            "incomplete_bar",
            current_bar.updated_at or current_bar.received_at,
        )

    if completed_bars:
        latest = completed_bars[-1]

        return latest.close, "completed_close", latest.end_at

    return None, None, None

def build_market_technical_snapshot(
    *,
    symbol: str,
    quote: Quote | None,
    bars: list[Bar],
    is_live_query: bool,
) -> MarketTechnicalSnapshot:
    """组装某只证券的确定性技术特征快照。

    该函数负责协调已有的技术指标和价格结构计算，
    本身不实现具体指标公式。
    """
    inputs = prepare_technical_inputs(
        quote=quote,
        bars=bars,
        is_live_query=is_live_query,
    )

    completed_bars = inputs.completed_bars

    current_bar = inputs.current_bar

    current_price, price_source, price_at = resolve_current_price(
        quote=inputs.quote,
        current_bar=current_bar,
        completed_bars=completed_bars,
    )

    latest_completed_close = (
        completed_bars[-1].close
        if completed_bars
        else None
    )
    closed = [bar.close for bar in completed_bars]
    atr14 = calculate_atr(completed_bars)

    price_structure = build_price_structure_snapshot(
        completed_bars=completed_bars,
        current_price=current_price,
        atr14=atr14,
    )
    current_bar_structure = None
    if current_bar is not None and current_price is not None:
        current_bar_structure = calculate_current_bar_structure(
            current_bar=current_bar,
            current_price=current_price,
            previous_close=latest_completed_close,
        )

    volume_features = build_volume_features(completed_bars)

    return MarketTechnicalSnapshot(
        symbol=symbol.strip().upper(),
        calculation_version=TECHNICAL_CALCULATION_VERSION,
        current_price=current_price,
        price_source=price_source,
        price_at=price_at,
        latest_completed_close=latest_completed_close,
        ma5=calculate_ma(closed, period=5),
        ma20=calculate_ma(closed, period=20),
        ma50=calculate_ma(closed, period=50),
        return_5d_pct=calculate_return(closed, period=5),
        return_20d_pct=calculate_return(closed, period=20),
        atr14=atr14,
        price_structure=price_structure,
        current_bar_structure=current_bar_structure,
        volume_features=volume_features,
    )
