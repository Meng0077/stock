from datetime import datetime

from pydantic import BaseModel, ConfigDict

from stock_agent.macro.models.fed import FedMedianProjection, FedPolicySnapshot
from stock_agent.macro.models.release import MacroReleaseEvent
from stock_agent.macro.models.treasury import TreasurySnapshot


class MacroSnapshot(BaseModel):
    """截至 as_of 可用于研究的宏观环境快照。

    注意：
        不要求所有模块的统计日期相同。

    例如：
        CPI 可能对应 8 月；
        非农可能对应 8 月；
        Initial Claims 对应最近一个周六；
        Treasury 对应最近一个交易日。

    as_of 表示：
        本次研究允许使用信息的截止时间。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: datetime

    # 最近发生的宏观数据发布事件。
    recent_releases: list[MacroReleaseEvent]
    fed_policy: FedPolicySnapshot | None
    fed_projections: list[FedMedianProjection]
    treasury: TreasurySnapshot | None
    warnings: list[str]
