from datetime import datetime
from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from stock_agent.market.schemas import Bar

IntradaySession = Literal[
    "pre",
    "regular",
    "post",
    "overnight",
    "unknown",
]


class IntradayBar(Bar):
    """一根分钟级 OHLCV 行情。"""
    model_config = ConfigDict(
        extra="forbid",
    )

    # 当前 Day26 先支持 1 分钟。
    timeframe: Literal["1m"] = "1m"

    # 本根 K 线实际所属的交易时段。
    session: IntradaySession


class HistoricalMinuteBarsRequest(BaseModel):
    """指定时间区间的历史分钟行情请求。"""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    symbol: str = Field(min_length=1)
    start_at: AwareDatetime
    end_at: AwareDatetime

    # 本次研究允许使用数据的截止时间。
    as_of: AwareDatetime

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.as_of < self.end_at:
            raise ValueError("historical window must not end after as_of")

        if self.start_at >= self.end_at:
            raise ValueError("start_at must be earlier than end_at")
        return self
