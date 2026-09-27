from datetime import datetime
from typing import Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

QUALITY_RULE_VERSION = "quality-v1"

class QualityIssue(BaseModel):
    """描述一项具体的数据质量问题。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    code: str = Field(min_length=1)

    message: str = Field(min_length=1)

    details: dict[str, Any] = Field(
        default_factory=dict,
    )


QualityStatus = Literal[
    "usable",
    "degraded",
    "rejected",
]

DataKind = Literal[
    "quote",
    "bars",
    "macro",
]

QualityPurpose = Literal[
    "current_price",
    "daily_technical",
    "macro_research",
    "market_reaction",
]


class DataQualityResult(BaseModel):
    model_config=ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    data_kind: DataKind

    target_id: str = Field(min_length=1)

    purpose: QualityPurpose

    status: QualityStatus

    issues: list[QualityIssue] = Field(
        default_factory=list
    )

    as_of: AwareDatetime

    rule_version: str = QUALITY_RULE_VERSION

    @model_validator(mode="after")
    def validate_status_and_issues(self) -> Self:

        if self.status == "usable" and self.issues:
            raise ValueError("usable result must not contain issues")

        if self.status in  {"degraded", "rejected"}:
            if not self.issues:
                raise ValueError("degraded/rejected result requires issues")

        return self
