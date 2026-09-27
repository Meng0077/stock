
from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)

from stock_agent.quality.models import DataQualityResult

ReportStatus = Literal[
    "usable",
    "degraded",
    "rejected",
    "not_assessed",
]

class DataQualityReport(BaseModel):
    """一次研究任务的数据质量汇总报告。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    as_of: AwareDatetime

    # Quote、Bar、Macro 各自的检查结果。
    results: list[DataQualityResult] = Field(
        default_factory=list,
    )

    # Provider 或 Builder 已经产生的警告。
    source_warnings: list[str] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_results(self) -> Self:
        """检查所有子结果属于同一次研究。"""

        seen = set()

        for result in self.results:
            # 不是同一批的
            if result.as_of != self.as_of:
                raise ValueError( "quality result as_of mismatch")

            identity = (
                result.data_kind,
                result.target_id,
                result.purpose,
            )

            # 重复的
            if identity in seen:
                raise ValueError("duplicate quality result")

            seen.add(identity)

        return self

    @computed_field
    @property
    def overall_status(self) -> ReportStatus:
        """汇总已经检查的数据状态。"""
        if not self.results:
            return "not_assessed"

        statuses = {
            result.status
            for result in self.results
        }

        if statuses == {"rejected"}:
            return "rejected"

        if statuses == {"usable"} and not self.source_warnings:
            return 'usable'

        return "degraded"