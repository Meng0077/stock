from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from stock_agent.market.schemas import Bar

class VolumeFeatures(BaseModel):
    """基于已完成日 K 计算的成交量特征。

    所有 RVOL 和趋势比值都使用倍数表示。
    例如 1.8 表示基准成交量的 1.8 倍。
    """

    model_config = ConfigDict(extra="forbid")

    # 最新完成日 K 的时间和成交量。
    latest_completed_at: datetime | None
    latest_volume: int | None

    # 技术分析层原样使用提供方返回的成交量，不在本地做复权。
    volume_adjustment: Literal["provider_reported"]

    # 最新完成日之前 20 个交易日的平均成交量。
    baseline_volume_20d: Decimal | None

    # 包含最新完成日的最近 5 日平均成交量。
    avg_volume_5d: Decimal | None

    # 最新完成日成交量 / 前 20 日平均成交量。
    rvol: Decimal | None

    # 最近 5 日平均成交量 / 前 20 日平均成交量。
    volume_trend_ratio: Decimal | None



def calculate_average_volume(
    volumes: list[int],
    *,
    period: int,
) -> Decimal | None:
    """计算最近 period 根 K 的平均成交量。

    Args:
        volumes: 按时间从旧到新排列的成交量。
        period: 参与平均的交易日数量。

    Returns:
        平均成交量。数据不足时返回 None。

    输入来自已校验的 Bar，不重复校验成交量非负。
    """

    if len(volumes) < period:
        return None

    return (
        Decimal(sum(volumes[-period:]))
        / Decimal(period)
    )


def build_volume_features(
    completed_bars: list[Bar],
) -> VolumeFeatures:
    """构建已完成日 K 的成交量特征。

    Args:
        completed_bars:
            按时间从旧到新排列的完成日 K。

    Returns:
        最新完成日的成交量特征。
        历史不足时，无法计算的字段返回 None。

    不负责：
        - 获取行情；
        - 盘中成交量预测；
        - 判断价格趋势；
        - 生成交易信号。
    """

    if not completed_bars:
        return VolumeFeatures(
            latest_completed_at=None,
            latest_volume=None,
            volume_adjustment="provider_reported",
            baseline_volume_20d=None,
            avg_volume_5d=None,
            rvol=None,
            volume_trend_ratio=None,
        )

    volumes = [
        bar.volume
        for bar in completed_bars
    ]

    latest = completed_bars[-1]

    # 前 20 日基准：排除最新完成日。
    baseline = calculate_average_volume(
        volumes[:-1],
        period=20,
    )

    # 最近 5 日：包含最新完成日。
    avg5 = calculate_average_volume(volumes, period=5)

    rvol = None
    trend_ratio = None

    # 成交量为 0 是合法数据；
    # 基准为 0 时，倍数没有定义。
    if baseline is not None and baseline > 0:
        rvol = (
            Decimal(latest.volume)
            / baseline
        )

        if avg5 is not None:
            trend_ratio = avg5 / baseline

    return VolumeFeatures(
        latest_completed_at=latest.end_at,
        latest_volume=latest.volume,
        volume_adjustment="provider_reported",
        baseline_volume_20d=baseline,
        avg_volume_5d=avg5,
        rvol=rvol,
        volume_trend_ratio=trend_ratio,
    )
