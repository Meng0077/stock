"""D04 Task 8：只公开固定错误码、阶段和安全提示。"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ErrorCode = Literal[
    "invalid_json",
    "invalid_output",
    "invalid_evidence",
    "data_mode_mismatch",
    "incomplete_response",
    "model_refusal",
    "invalid_tool_call",
    "model_timeout",
    "model_error",
    "tool_timeout",
    "total_timeout",
    "cancelled",
    "budget_exhausted",
]
ErrorStage = Literal["model", "tool", "validation", "task"]

_ERROR_DETAILS: dict[ErrorCode, tuple[ErrorStage, str]] = {
    "invalid_json": ("validation", "模型输出不是有效的 JSON。"),
    "invalid_output": ("validation", "模型输出不符合结果结构。"),
    "invalid_evidence": ("validation", "结果引用了未提供的证据。"),
    "data_mode_mismatch": ("validation", "结果标记的资料模式与实际资料不符。"),
    "incomplete_response": ("model", "模型响应不完整。"),
    "model_refusal": ("model", "模型拒绝生成结果。"),
    "invalid_tool_call": ("tool", "模型工具调用格式不符合要求。"),
    "model_timeout": ("model", "模型请求超时。"),
    "model_error": ("model", "模型调用失败。"),
    "tool_timeout": ("tool", "工具调用超时。"),
    "total_timeout": ("task", "任务总时限已到。"),
    "cancelled": ("task", "任务已取消。"),
    "budget_exhausted": ("task", "本次任务的调用预算已用尽。"),
}


class PublicError(BaseModel):
    """可对外记录的错误；字段必须与固定错误码的定义一致。"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    code: ErrorCode
    message: str = Field(min_length=1)
    stage: ErrorStage

    @model_validator(mode="after")
    def check_fixed_details(self) -> Self:
        expected_stage, expected_message = _ERROR_DETAILS[self.code]
        if (self.stage, self.message) != (expected_stage, expected_message):
            raise ValueError("公开错误的阶段或提示与错误码不匹配")
        return self


def make_public_error(code: ErrorCode) -> PublicError:
    """按固定错误码生成安全对象；入参为 code，出参为 PublicError。"""
    details = _ERROR_DETAILS.get(code)
    if details is None:
        raise ValueError("未知公开错误码")
    stage, message = details
    return PublicError(code=code, message=message, stage=stage)
