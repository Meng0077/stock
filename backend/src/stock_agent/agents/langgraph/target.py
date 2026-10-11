from typing import Literal

from langchain_core.language_models import (
    BaseChatModel,
)
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from stock_agent.agents.context import (
    ResearchContext,
)
from stock_agent.agents.langgraph.state import (
    ResearchState,
)
from stock_agent.company.resolver import (
    TargetResolution,
    resolve_targets,
)


async def resolve_target_node(
    state: ResearchState,
    runtime: Runtime[ResearchContext],
    *,
    model: BaseChatModel,
) -> dict[str, object]:
    """
    解析本次研究请求的证券 target。

    第一次进入：
        解析原始 question。

    clarification 后再次进入：
        只解析用户补充的 target 表达。

    resolved 后，
    把 canonical ticker 写回 ResearchRequest。
    """
    text = state["target_clarification"]

    # 已归一化的内部 ResearchRequest
    # 可以直接进入后续节点；
    # 自然语言 API 创建的请求 company_id=None，
    # 仍会走完整 Target Resolver。
    request_company_id = state["request"].company_id
    if text is None and request_company_id is not None:
        company_id = request_company_id.strip().upper()
        return {
            "request": state["request"].model_copy(
                update={"company_id": company_id}
            ),
            "target_resolution": TargetResolution(
                resolved_targets=[company_id]
            ),
        }

    if text is None:
        target_text = state["request"].question
    else:
        target_text = text

    resolution = await resolve_targets(
        target_text,
        model=model,
        fallback_provider_factory=runtime.context.market_provider_factory,
    )

    update: dict[str, object] = {"target_resolution": resolution}

    if resolution.status == "resolved":
        company_id = resolution.resolved_targets[0]

        # Planner / Research 后面统一读取
        # request.company_id，不需要再理解 target。
        update["request"] = state["request"].model_copy(
            update={"company_id": company_id}
        )
    elif resolution.status == "absent" and text is None:
        # 原始问题确实没有证券 target，
        update["request"] = state["request"].model_copy(
            update={"company_id": None}
        )

    return update


TargetRoute = Literal[
    "planner",
    "clarify_target",
]


def route_after_target(
    state: ResearchState,
) -> TargetRoute:
    """
    根据 Target Resolution
    决定直接研究还是向用户澄清。
    """
    resolution = state["target_resolution"]
    if resolution is None:
        raise RuntimeError("target resolution is missing")

    if resolution.status == "resolved":
        return "planner"
    if resolution.status == "absent":
        # 原始 question 本身没有 target，
        # 可以进入 macro-only Planner。
        if state["target_clarification"] is None:
            return "planner"

        # clarification 内容仍然没能
        # 确认一个证券，继续问。
        return "clarify_target"
    return "clarify_target"


def clarify_target_node(
    state: ResearchState,
) -> dict[str, object]:
    """
    暂停 Workflow，
    请求用户明确一个最终研究标的。

    用户回答后，
    交回 resolve_target_node 再验证。
    """
    resolution = state["target_resolution"]
    if resolution is None:
        raise RuntimeError("target resolution is missing")

    candidates: list[str] = []

    for ticker in resolution.resolved_targets:
        if ticker not in candidates:
            candidates.append(ticker)

    for target in resolution.ambiguous_targets:
        for ticker in target.candidates:
            if ticker not in candidates:
                candidates.append(ticker)

    if resolution.status == "multiple":
        message = (
            "当前问题包含多个证券标的。"
            "当前工作流一次研究一个证券，"
            "请回复你要研究的一个 ticker。"
        )

    elif resolution.status == "ambiguous":
        message = (
            "当前证券标的存在歧义，"
            "请回复你要研究的具体 ticker。"
        )
    elif resolution.status == "absent":
        message = (
            "这个问题需要具体证券标的，"
            "请回复公司名称或 ticker。"
        )
    else:
        message = (
            "目前无法确定你指的是哪只证券，"
            "请回复更明确的公司名称或 ticker。"
        )
    answer = interrupt(
        {
            "type": (
                "target_clarification"
            ),
            "message": message,
            "candidates": candidates,
        }
    )

    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("target clarification must be a non-empty string")

    return {
        "target_clarification": answer.strip(),
    }
