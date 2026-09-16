"""D08：Manual Agent 与 LangChain Agent 的行为对照模型和归一化入口。

本模块只负责把两种 Agent 已有的运行结果转换成共同观察口径，不执行模型、
不调用工具，也不在 D08 修复 D09 才处理的 timeout、budget、evidence 或错误映射。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AgentKind = Literal["manual", "langchain"]
COMPARISON_CASE_IDS = ("D05-02", "D05-06", "D05-07", "D05-10")


class AgentObservation(BaseModel):
    """一条 Agent 运行的共同观察字段；不要求两边内部状态完全相同。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    agent_kind: AgentKind
    terminal_status: str
    model_request_count: int = Field(ge=0)
    tool_requests: list[str]
    tool_results: list[str]
    handler_call_count: int = Field(ge=0)
    message_types: list[str]
    error_type: str | None = None


class CaseComparison(BaseModel):
    """同一 case_id 的 Manual/LangChain 观察结果和人工差异说明。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    manual: AgentObservation
    langchain: AgentObservation
    differences: list[str]


def select_comparison_cases(
    cases: list[dict[str, Any]],
    case_ids: tuple[str, ...] = COMPARISON_CASE_IDS,
) -> list[dict[str, Any]]:
    """输入 D05 案例和目标 ID；按目标顺序输出唯一案例，缺失或重复时拒绝。"""
    # TODO D08-Step-2.1：只选择 D05-02/06/07/10，不复制或修改原案例。
    raise NotImplementedError


def observe_manual_record(record: dict[str, Any]) -> AgentObservation:
    """输入 D05 Manual 运行记录；输出共同口径的 Manual 观察结果。"""
    # TODO D08-Step-3.1：读取终态、模型次数、工具顺序、handler 次数和消息类型。
    raise NotImplementedError


def observe_langchain_state(
    *,
    case_id: str,
    state: dict[str, Any] | None,
    model_request_count: int,
    handler_call_count: int,
    error: BaseException | None,
) -> AgentObservation:
    """输入 LangChain state/计数/异常；输出共同口径的 LangChain 观察结果。"""
    # TODO D08-Step-4.1：只观察现状；异常保留固定类型名，不提前做 D09 错误映射。
    raise NotImplementedError


def compare_case(
    manual: AgentObservation,
    langchain: AgentObservation,
) -> CaseComparison:
    """输入同一案例的两条观察；输出逐字段差异，case_id 不一致时拒绝。"""
    # TODO D08-Step-5.1：比较调用次数、错误、工具顺序和消息类型，不比较代码行数。
    raise NotImplementedError
