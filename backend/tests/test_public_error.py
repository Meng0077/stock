"""公开错误只能使用固定类别和安全提示。"""

from typing import get_args

import pytest
from pydantic import ValidationError

from stock_agent.schemas.errors import ErrorCode, PublicError, make_public_error


def test_every_error_code_builds_only_public_fields():
    for code in get_args(ErrorCode):
        error = make_public_error(code)
        assert error.code == code
        assert error.stage in {"model", "tool", "validation", "task"}
        assert set(error.model_dump()) == {"code", "message", "stage"}
        assert error.message


def test_unknown_code_and_arbitrary_error_text_are_rejected():
    with pytest.raises(ValueError, match="未知公开错误码"):
        make_public_error("PRIVATE_PROVIDER_ERROR")

    with pytest.raises(ValidationError):
        PublicError(
            code="model_error",
            message="PRIVATE_PROVIDER_ERROR",
            stage="model",
        )


def test_stage_mismatch_and_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        PublicError(code="cancelled", message="任务已取消。", stage="model")

    with pytest.raises(ValidationError):
        PublicError(
            code="cancelled",
            message="任务已取消。",
            stage="task",
            raw_exception="PRIVATE_PROVIDER_ERROR",
        )
