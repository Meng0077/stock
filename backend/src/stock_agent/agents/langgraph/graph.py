from functools import partial

from langchain_core.language_models import (
    BaseChatModel,
)
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
)
from stock_agent.agents.langgraph.research import (
    research_node,
)
from stock_agent.agents.langgraph.state import (
    ResearchState,
)
from stock_agent.schemas.research import ResearchRequest

def build_research_graph(
    model: BaseChatModel,
):
    """
    构建股票研究 LangGraph。

    Workflow:

        START
          ↓
        planner
          ↓
        research
          ↓
        checker
          ├─ retry  → research
          └─ answer → answer
                       ↓
                      END

    当前不配置 checkpointer。
    Checkpoint / resume 属于 Day37。
    """
    planner_node = partial(plan_node, model=model)
    answer_node_with_model = partial(answer_node, model=model)

    builder = StateGraph(ResearchState, context_schema=ResearchContext)


    builder.add_node("planner", planner_node)
    builder.add_node("research", research_node)
    builder.add_node("checker", checker_node)
    builder.add_node("answer", answer_node_with_model)

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "research")
    builder.add_edge("research", "checker")
    builder.add_conditional_edges(
        "checker", route_after_check,
        {
            "research": "research",
            "answer": "answer"
        }
    )

    builder.add_edge("answer", END)

    return builder.compile()


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
    }
