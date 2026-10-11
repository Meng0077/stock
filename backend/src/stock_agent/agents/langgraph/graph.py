from functools import partial

from langchain_core.language_models import (
    BaseChatModel,
)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import (
    END,
    START,
    StateGraph,
)

from stock_agent.agents.context import (
    ResearchContext,
)
from stock_agent.agents.langgraph.answer import (
    answer_node,
)
from stock_agent.agents.langgraph.checker import (
    checker_node,
    route_after_check,
)
from stock_agent.agents.langgraph.planner import (
    plan_node,
    route_after_plan,
)
from stock_agent.agents.langgraph.research import (
    research_node,
)
from stock_agent.agents.langgraph.state import (
    ResearchState,
)
from stock_agent.agents.langgraph.target import (
    clarify_target_node,
    resolve_target_node,
    route_after_target,
)
from stock_agent.schemas.research import ResearchRequest


def build_research_graph(
    model: BaseChatModel,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """
    构建股票研究 LangGraph。

    Workflow:

        START
          ↓
        resolve_target
          ├─ clarify_target → resolve_target
          └─ planner
               ├─ clarify_target → resolve_target
               └─ research
                    ↓
                  checker
                    ├─ retry  → research
                    └─ answer → END

    checkpointer 用于保存 interrupt 状态并支持 resume。
    """
    target_node = partial(resolve_target_node, model=model)
    planner_node = partial(plan_node, model=model)
    answer_node_with_model = partial(answer_node, model=model)

    builder = StateGraph(ResearchState, context_schema=ResearchContext)

    builder.add_node("resolve_target", target_node)
    builder.add_node("clarify_target", clarify_target_node)
    builder.add_node("planner", planner_node)
    builder.add_node("research", research_node)
    builder.add_node("checker", checker_node)
    builder.add_node("answer", answer_node_with_model)

    builder.add_edge(START, "resolve_target")
    builder.add_conditional_edges(
        "resolve_target", route_after_target,
        {
            "planner": "planner",
            "clarify_target": "clarify_target",
        },
    )
    # 用户补充 target 后，
    # 不直接进入 Planner，
    # 必须再次经过 Target Resolver 验证。
    builder.add_edge("clarify_target", "resolve_target")
    builder.add_conditional_edges(
        "planner", route_after_plan,
        {
            "research": "research",
            "clarify_target": "clarify_target",
        }
    )
    builder.add_edge("research", "checker")
    builder.add_conditional_edges(
        "checker", route_after_check,
        {
            "research": "research",
            "answer": "answer",
        },
    )

    builder.add_edge("answer", END)

    return builder.compile(checkpointer=checkpointer)


def build_initial_state(
    request: ResearchRequest,
) -> ResearchState:
    """
    为一次新的 Research Workflow
    创建初始 State。
    """
    return {
        "request": request,
        "plan": None,
        "results": {},
        "missing_information": [],
        "retry_count": 0,
        "research_status": None,
        "output": None,
        "target_resolution": None,
        "target_clarification": None,
    }
