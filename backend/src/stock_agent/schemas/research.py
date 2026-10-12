"""D02：数据模型不是大语言模型，而是输入数据的规则。"""

from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from stock_agent.schemas.research_output import RequestDataMode, ResearchOutput


class ResearchRequest(BaseModel):
    # 未声明字段拒绝；字符串先去除首尾空白；赋值时也重新校验。
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, validate_assignment=True
    )

    company_ids: list[str] = Field(
        default_factory=list,
        max_length=20,
    )
    question: str = Field(min_length=1, max_length=2000)
    data_mode: RequestDataMode
    # 允许带时区的日期字符串转换为 datetime；没有时区则拒绝。
    as_of: AwareDatetime


class ResearchInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid", validate_assignment=True
    )
    message: str = Field(
        min_length=1,
        max_length=2000,
    )

    thread_id: UUID | None = None


class ResearchResponse(BaseModel):
    run_id: str
    status: str
    result: ResearchOutput | None
    error: dict[str, Any] | None
    clarification: dict[str, Any] | None = None


class ResearchResumeInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    thread_id: str = Field(
        min_length=1,
    )

    answer: str = Field(
        min_length=1,
        max_length=2000,
    )


ResearchWorkflowStatus = Literal[
    "needs_input",
    "completed",
    "failed",
    "cancelled",
]


class ResearchWorkflowResponse(BaseModel):
    thread_id: str

    status: ResearchWorkflowStatus

    result: str | None = None

    clarification: (
        dict[str, Any] | None
    ) = None

    error: dict[str, Any] | None = None
