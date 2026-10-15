from typing import Literal

from langchain_core.language_models import BaseChatModel
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from stock_agent.agents.context import ResearchContext
from stock_agent.agents.langgraph.state import ResearchState
from stock_agent.company.registry import lookup_security
from stock_agent.company.resolver import TargetResolution, resolve_targets


def merge_company_ids(
    current: list[str],
    resolved: list[str],
) -> list[str]:
    company_ids = list(current)

    for company_id in resolved:
        normalized = company_id.strip().upper()

        if normalized not in company_ids:
            company_ids.append(normalized)

    return company_ids


async def resolve_target_node(
    state: ResearchState,
    runtime: Runtime[ResearchContext],
    *,
    model: BaseChatModel,
) -> dict[str, object]:
    """
    解析整个研究请求当前已经明确的证券 target。

    第一次进入：
        解析原始 question。

    clarification 后再次进入：
        验证用户本次提交的结构化 ticker 列表。

    resolved_targets 可以包含一个或多个 ticker。
    """
    answer = state["target_clarification"]

    request = state["request"]

    # 已归一化的内部 ResearchRequest
    # 可以直接进入后续节点；
    # 自然语言 API 创建的请求 company_ids=[]，
    # 仍会走完整 Target Resolver。
    request_company_ids = request.company_ids
    if answer is None and request_company_ids:
        company_ids = merge_company_ids([], request_company_ids)
        return {
            "request": state["request"].model_copy(
                update={"company_ids": company_ids}
            ),
            "target_resolution": TargetResolution(resolved_targets=company_ids),
        }

    # resume
    if answer is not None:
        symbols = list(dict.fromkeys(item.strip().upper() for item in answer))
        resolved = []
        unresolved = []
        for symbol in symbols:
            security = lookup_security(
                symbol,
                fallback_provider_factory=runtime.context.market_provider_factory,
            )

            if security is None:
                unresolved.append(symbol)
            elif security.symbol not in resolved:
                resolved.append(security.symbol)
        company_ids = merge_company_ids(request_company_ids, resolved)

        resolution = TargetResolution(
            resolved_targets=company_ids,
            unresolved_mentions=unresolved,
        )

        return {
            "request": request.model_copy(update={"company_ids": company_ids}),
            "target_resolution": resolution,
            "target_clarification": answer if unresolved else None,
        }

    # 首次请求
    target_text = request.question
    resolution = await resolve_targets(
        target_text,
        model=model,
        fallback_provider_factory=runtime.context.market_provider_factory,
    )

    company_ids = merge_company_ids(request_company_ids, resolution.resolved_targets)
    resolution = resolution.model_copy(
        update={"resolved_targets": company_ids}
    )

    update: dict[str, object] = {
        "target_resolution": resolution,
        "request": request.model_copy(update={"company_ids": company_ids}),
    }

    if resolution.status == "resolved":
        update["target_clarification"] = None
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

    # Resolver 负责分类；
    # Router 只消费 status。
    # 只要还有证券没有确定，
    # 就不能进入 Planner。
    if resolution.status == "resolved":
        return "planner"

    if resolution.status in {"ambiguous", "unresolved"}:
        return "clarify_target"

    if resolution.status == "absent":
        if state["target_clarification"] is None:
            return "planner"
        return "clarify_target"
    raise RuntimeError("unknown target resolution status")


def clarify_target_node(
    state: ResearchState,
) -> dict[str, object]:
    """
    暂停 Workflow，
    请求用户补充仍未确定的证券 target。

    resume answer 是用户本次提交的完整 ticker 列表，
    下一轮 resolve_target_node 会逐个验证。
    """
    resolution = state["target_resolution"]
    if resolution is None:
        raise RuntimeError("target resolution is missing")

    ambiguous_targets = [
        {
            "mention": target.mention,
            "candidates": target.candidates,
        }
        for target in resolution.ambiguous_targets
    ]

    unresolved_mentions = list(resolution.unresolved_mentions)

    if resolution.status == "ambiguous":
        message = "当前证券标的存在歧义，请回复你要研究的具体 ticker。"
    elif resolution.status == "unresolved":
        message = "当前仍有证券标的无法确定，请补充更明确的公司名称或 ticker。"
    elif resolution.status == "absent":
        message = "这个问题需要具体证券标的，请回复公司名称或 ticker。"
    else:
        # resolved 状态不应进入澄清流程
        raise RuntimeError("resolved target should not enter clarification")
    answer = interrupt(
        {
            "type": "target_clarification",
            "message": message,
            "ambiguous_targets": ambiguous_targets,
            "unresolved_mentions": unresolved_mentions,
        }
    )
    if (
        not isinstance(answer, list)
        or not answer
        or any(not isinstance(item, str) or not item.strip() for item in answer)
    ):
        raise RuntimeError("target clarification must be a non-empty list of tickers")
    return {"target_clarification": answer}
