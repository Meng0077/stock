"""D06 Step 3：定义 API 与 Manual Agent 之间的结构化契约。

前置输入：
- ResearchRequest 已在 stock_agent.schemas.research 中实现，直接复用。
- ResearchOutput 已在 stock_agent.schemas.research_output 中实现，直接复用。
- PublicError 已在 stock_agent.schemas.errors 中实现，直接复用。

本文件要完成：
- RunStatus：一次同步运行允许出现的确定终态。
- AgentRunResult：Manual Agent runner 返回给应用层的结果。
- RunResponse：POST /api/runs 返回给客户端的安全响应。
- 成功/失败字段组合的跨字段校验。

不要在这里：
- 重新定义 ResearchRequest；
- 使用无约束 dict 代替 ResearchOutput / PublicError；
- 保存原始异常、堆栈、请求头或 API Key。
"""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from stock_agent.schemas.errors import PublicError
from stock_agent.schemas.research_output import ResearchOutput


# TODO D06-Step-3.1：确认以下终态与现有 model_loop 的事件完全一致。
RunStatus = Literal[
    "completed",
    "insufficient_information",
    "failed",
    "cancelled",
]


class AgentRunResult(BaseModel):
    """Manual Agent 的结构化返回值。

    输入来源：run_manual_agent() 根据 Agent 的最终事件和 final_output 构造。
    输出去向：create_run() 把它映射为 RunResponse。

    字段：
    - run_id：本次运行的唯一 UUID，由 HTTP 层生成并传入 Agent。
    - status：本次运行的确定终态。
    - result：成功或信息不足时的 ResearchOutput；失败时必须为 None。
    - error：失败或取消时的安全 PublicError；正常结果时必须为 None。
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    run_id: UUID
    status: RunStatus
    result: ResearchOutput | None = None
    error: PublicError | None = None

    # D06-Step-3.2：校验以下组合规则。
    # - completed / insufficient_information：必须有 result，必须没有 error；
    # - result.status 必须与外层 status 一致；
    # - failed / cancelled：必须没有 result，必须有 error；
    # - cancelled 只能配 cancelled 错误码。
    @model_validator(mode="after")
    def check_terminal_payload(self) -> Self:
        """输入当前模型；校验终态、结果和错误的组合；返回校验后的自身。"""
        successful_statuses = {"completed", "insufficient_information"}

        if self.status in successful_statuses:
            if self.result is None or self.error is not None:
                raise ValueError(
                    "completed / insufficient_information 必须有 result 且没有 error"
                )
            if self.result.status != self.status:
                raise ValueError("外层 status 必须与 result.status 一致")
        else:
            if self.result is not None or self.error is None:
                raise ValueError("failed / cancelled 必须没有 result 且必须有 error")
            if (self.status == "cancelled") != (self.error.code == "cancelled"):
                raise ValueError("cancelled 状态与 cancelled 错误码必须同时出现")

        return self

class RunResponse(BaseModel):
    """POST /api/runs 的公开响应。

    输入：一个已通过校验的 AgentRunResult。
    输出：可安全 JSON 序列化的 run_id、status、result、error。

    公开模型与内部模型暂时字段相同，但仍单独定义，避免未来把内部事件、
    token 用量或异常细节意外暴露给客户端。
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    run_id: UUID
    status: RunStatus
    result: ResearchOutput | None = None
    error: PublicError | None = None

    # D06-Step-3.3：显式复制允许公开的字段；未来内部新增字段不会自动泄露。
    @classmethod
    def from_agent_result(cls, run: AgentRunResult) -> "RunResponse":
        """输入内部 AgentRunResult；只复制公开字段；输出 RunResponse。"""
        return cls(
            run_id=run.run_id,
            status=run.status,
            result=run.result,
            error=run.error,
        )
