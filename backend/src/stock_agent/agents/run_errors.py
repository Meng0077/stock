"""把内部运行异常映射为允许公开的固定错误码。"""

import httpx
from pydantic import ValidationError

from stock_agent.schemas.errors import ErrorCode


def error_code_from_exception(
    error: Exception,
    *,
    total_timeout_expired: bool = False,
) -> ErrorCode:
    """输入内部异常和总超时状态；输出固定安全错误码，不返回异常正文。"""
    if isinstance(error, httpx.TimeoutException):
        return "model_timeout"

    if isinstance(error, TimeoutError):
        return "total_timeout" if total_timeout_expired else "model_error"

    if isinstance(
        error,
        (
            httpx.HTTPStatusError,
            httpx.RequestError,
            ValidationError,
            ValueError,
        ),
    ):
        return "model_error"

    return "model_error"


def safe_message_from_exception(
    error: Exception,
    *,
    total_timeout_expired: bool = False,
) -> str:
    """输入内部异常和总超时状态；输出不含异常正文的安全日志提示。"""
    code = error_code_from_exception(
        error,
        total_timeout_expired=total_timeout_expired,
    )
    if code == "total_timeout":
        return "任务总时限已到。"
    if code == "model_timeout":
        return "模型请求超时。"
    if isinstance(error, httpx.HTTPStatusError):
        return "模型服务返回错误状态。"
    if isinstance(error, httpx.RequestError):
        return "模型连接失败。"
    if isinstance(error, (ValidationError, ValueError)):
        return "模型响应解析失败。"
    return "模型调用失败；原始异常已隐藏。"
