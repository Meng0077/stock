from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


MarketDataMode = Literal[
    "fixture",
    "historical",
    "live",
]

MarketSession = Literal[
    "overnight",
    "pre",
    "regular",
    "post",
    "closed",
    "unknown",
]

BarTimeframe = Literal["1d", "1m"]

PriceAdjustment = Literal[
    "raw",
    "split_adjusted",
    "forward_adjusted",
]

class Quote(BaseModel):
    """一条股票报价。

    quoted_at 是行情发生时间。
    received_at 是系统收到报价的时间。

    二者必须区分，不能把收到数据的时间
    当成交易所报价的时间。
    """
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    price: Decimal = Field(gt=0)
    currency: str = Field(min_length=1)

    quoted_at: datetime
    received_at: datetime

    session: MarketSession
    data_mode: MarketDataMode

    # None 表示供应商没有提供可靠的延迟信息。
    is_delayed: bool | None

    source: str = Field(min_length=1)

    @field_validator("quoted_at", "received_at")
    @classmethod
    def require_timezone(cls, value: datetime)-> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")

        return value


class Bar(BaseModel):
    """一根 OHLCV K 线。

    每根 Bar 对应一个确定的时间区间。
    is_complete 明确标识当前 K 线是否已经完成。

    adjustment 用于区分原始价格和拆股复权价格，
    避免不同计算口径混用。
    """
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    timeframe: BarTimeframe

    start_at: datetime
    end_at: datetime

    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)

    volume: int = Field(ge=0)

    is_complete: bool
    adjustment: PriceAdjustment

    # 当前这份 Bar 快照实际更新到的时间。
    updated_at: datetime | None
    received_at: datetime

    source: str = Field(min_length=1)
    data_mode: MarketDataMode

    @field_validator(
        "start_at",
        "end_at",
        "updated_at",
        "received_at",
    )
    @classmethod
    def require_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        """要求 K 线时间具有明确时区。"""

        if value is None:
            return None

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")

        return value

    @model_validator(mode="after")
    def validate_ohlc(self) -> Self:
        """验证 K 线的时间区间和 OHLC 关系。"""
        if self.start_at >= self.end_at:
            raise ValueError("invalid bar time range")

        if self.high < max(
            self.open,
            self.close,
            self.low,
        ):
            raise ValueError("invalid high price")

        if self.low > min(
            self.open,
            self.close,
        ):
            raise ValueError("invalid low price")

        return self


@dataclass(frozen=True)
class _QuoteCandidate:
    """Longbridge Quote 转换过程中的临时候选值。

    只用于 mapper 内部，
    不会暴露给 Agent 上层。
    """

    price: Decimal
    quoted_at: datetime
    session: MarketSession
