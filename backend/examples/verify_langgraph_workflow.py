"""Day36 / Day38 LangGraph 真实 Live Smoke。

真实调用 DeepSeek、LangGraph、Longbridge 和 Macro Provider，
验收 start / interrupt / resume / macro-only，不提交交易订单。

运行：
PYTHONPATH=backend/src backend/.venv/bin/python \
    backend/examples/verify_langgraph_workflow.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from langchain_deepseek import ChatDeepSeek
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import SecretStr

from stock_agent.agents.context import ResearchContext
from stock_agent.agents.langgraph.graph import (
    build_initial_state,
    build_research_graph,
)
from stock_agent.llm_client import get_llm_config
from stock_agent.macro.config_factory import build_macro_snapshot_builder
from stock_agent.market.longbridge.config_factory import (
    build_longbridge_market_provider,
)
from stock_agent.schemas.research import ResearchRequest
from stock_agent.schemas.research_output import RequestDataMode


BACKEND = Path(__file__).resolve().parents[1]


async def run_case(
    *,
    graph: Any,
    question: str,
    data_mode: RequestDataMode,
    as_of: datetime,
    thread_id: str,
) -> tuple[dict[str, Any], ResearchContext, RunnableConfig]:
    request = ResearchRequest(
        company_ids=[],
        question=question,
        data_mode=data_mode,
        as_of=as_of,
    )
    context = ResearchContext(
        as_of=as_of,
        market_provider_factory=build_longbridge_market_provider,
        macro_builder_factory=build_macro_snapshot_builder,
        market_state="unknown",
    )
    graph_config = RunnableConfig(
        configurable={"thread_id": thread_id}
    )

    result = await graph.ainvoke(
        build_initial_state(request),
        context=context,
        config=graph_config,
    )
    return result, context, graph_config


async def resume_case(
    *,
    graph: Any,
    answer: str,
    context: ResearchContext,
    graph_config: RunnableConfig,
) -> dict[str, Any]:
    return await graph.ainvoke(
        Command(resume=answer),
        context=context,
        config=graph_config,
    )


def print_result(*, title: str, result: dict[str, Any]) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)

    plan = result.get("plan")
    request = result.get("request")
    resolution = result.get("target_resolution")
    print(
        "request:",
        request.model_dump(mode="json") if request is not None else None,
    )
    print(
        "target_resolution:",
        resolution.model_dump(mode="json")
        if resolution is not None
        else None,
    )
    print("research_status:", result.get("research_status"))
    print("retry_count:", result.get("retry_count"))
    print("missing_information:", result.get("missing_information"))
    print("result_keys:", sorted(result.get("results", {}).keys()))
    print(
        "plan:",
        plan.model_dump(mode="json") if plan is not None else None,
    )
    print()
    print("output:")
    print(result.get("output"))


def has_terminal_answer(result: dict[str, Any]) -> bool:
    return (
        result.get("research_status") in {"enough", "cannot_retry"}
        and bool(result.get("output"))
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(f"验收失败：{message}")


def get_clarification(result: dict[str, Any]) -> dict[str, Any]:
    interrupts = result.get("__interrupt__")
    if not interrupts:
        raise AssertionError("验收失败：Workflow 没有进入 interrupt")
    clarification = interrupts[0].value
    if not isinstance(clarification, dict):
        raise AssertionError("验收失败：clarification 格式错误")
    return clarification


async def main() -> int:
    config = get_llm_config(BACKEND / ".env")
    if config is None or config.provider != "deepseek":
        print(
            "配置错误：请在 backend/.env 配置 DeepSeek。",
            file=sys.stderr,
        )
        return 1

    timeout = float(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))
    model = ChatDeepSeek(
        model=config.model,
        api_key=SecretStr(config.api_key),
        temperature=0,
        timeout=timeout,
        max_retries=0,
        extra_body={"thinking": {"type": "disabled"}},
    )
    graph = build_research_graph(
        model,
        checkpointer=InMemorySaver(),
    )
    # 给真实 Provider 请求和 received_at 留出明确网络窗口。
    # MarketContext 仍然保持严格的 as_of 时间边界。
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)

    # =====================================================
    # Case 1：单标的直接完成
    # =====================================================

    trend_result, _, _ = await run_case(
        graph=graph,
        question="NVDA 当前走势怎么看",
        data_mode="live",
        as_of=as_of,
        thread_id="day38-case-1-trend",
    )
    print_result(title="CASE 1 - Resolved Trend", result=trend_result)

    require("__interrupt__" not in trend_result, "NVDA 走势问题不应 interrupt")
    require(
        trend_result["request"].company_ids == ["NVDA"],
        "NVDA 没有写入 ResearchRequest",
    )
    require(
        trend_result["target_resolution"].status == "resolved",
        "NVDA Target Resolution 不是 resolved",
    )
    require(has_terminal_answer(trend_result), "NVDA 走势问题没有最终回答")

    # =====================================================
    # Case 2：Macro only
    # =====================================================

    macro_result, _, _ = await run_case(
        graph=graph,
        question="最新 CPI 是多少",
        data_mode="mixed",
        as_of=as_of,
        thread_id="day38-case-2-macro-only",
    )
    print_result(
        title="CASE 2 - Macro Only",
        result=macro_result,
    )

    macro_plan = macro_result["plan"]
    require("__interrupt__" not in macro_result, "Macro-only 问题不应 interrupt")
    require(
        macro_result["target_resolution"].status == "absent",
        "Macro-only Target Resolution 不是 absent",
    )
    require(
        macro_result["request"].company_ids == [],
        "Macro-only 请求不应有 company_id",
    )
    require(macro_plan.needs_macro, "Macro-only Planner 没有要求 Macro")
    require(
        not any(
            (
                macro_plan.needs_company_profile,
                macro_plan.needs_quote,
                macro_plan.needs_technical,
                macro_plan.needs_decision,
                macro_plan.knowledge_question is not None,
                bool(macro_plan.financial_requests),
                macro_plan.needs_macro_reaction,
                macro_plan.needs_macro_reaction_history,
                macro_plan.needs_earnings_reaction,
                macro_plan.needs_earnings_reaction_history,
            )
        ),
        "Macro-only Planner 要求了额外证券能力",
    )
    require(
        "macro_snapshot" in macro_result["results"],
        "Macro-only 结果没有 macro_snapshot",
    )
    require(has_terminal_answer(macro_result), "Macro-only 问题没有最终回答")

    # =====================================================
    # Case 3：无 target 的 Quote 先澄清再恢复
    # =====================================================

    quote_interrupted, quote_context, quote_config = await run_case(
        graph=graph,
        question="现在股价多少",
        data_mode="mixed",
        as_of=as_of,
        thread_id="day38-case-3-quote-resume",
    )
    print_result(
        title="CASE 3A - Quote Needs Target",
        result=quote_interrupted,
    )

    quote_clarification = get_clarification(quote_interrupted)
    require(
        quote_interrupted["target_resolution"].status == "absent",
        "无 target 报价问题的初始状态不是 absent",
    )
    require(
        quote_interrupted["plan"].needs_quote,
        "无 target 报价问题没有规划 needs_quote",
    )
    require(
        quote_clarification["type"] == "target_clarification",
        "无 target 报价问题没有请求补充证券",
    )

    quote_completed = await resume_case(
        graph=graph,
        answer="NVDA",
        context=quote_context,
        graph_config=quote_config,
    )
    print_result(
        title="CASE 3B - Quote Resumed With NVDA",
        result=quote_completed,
    )
    require("__interrupt__" not in quote_completed, "NVDA 恢复后仍然 interrupt")
    require(
        quote_completed["request"].question == "现在股价多少",
        "Quote resume 改写了原始 question",
    )
    require(
        quote_completed["request"].company_ids == ["NVDA"],
        "Quote resume 没有写入 NVDA",
    )
    require(has_terminal_answer(quote_completed), "Quote resume 没有最终回答")

    # =====================================================
    # Case 4：Google 歧义澄清
    # =====================================================

    google_interrupted, google_context, google_config = await run_case(
        graph=graph,
        question="Google 怎么看",
        data_mode="mixed",
        as_of=as_of,
        thread_id="day38-case-4-google-resume",
    )
    print_result(
        title="CASE 4A - Google Ambiguous",
        result=google_interrupted,
    )

    google_clarification = get_clarification(google_interrupted)
    require(
        google_interrupted["target_resolution"].status == "ambiguous",
        "Google Target Resolution 不是 ambiguous",
    )
    require(
        {"GOOG", "GOOGL"}.issubset(google_clarification["candidates"]),
        "Google clarification 缺少 GOOG / GOOGL 候选",
    )

    google_completed = await resume_case(
        graph=graph,
        answer="GOOGL",
        context=google_context,
        graph_config=google_config,
    )
    print_result(
        title="CASE 4B - Google Resumed With GOOGL",
        result=google_completed,
    )
    require("__interrupt__" not in google_completed, "GOOGL 恢复后仍然 interrupt")
    require(
        google_completed["request"].question == "Google 怎么看",
        "Google resume 改写了原始 question",
    )
    require(
        google_completed["request"].company_ids == ["GOOGL"],
        "Google resume 没有写入 GOOGL",
    )
    require(has_terminal_answer(google_completed), "Google resume 没有最终回答")

    # =====================================================
    # Case 5：多标的不能静默选第一只
    # =====================================================

    multiple_interrupted, multiple_context, multiple_config = await run_case(
        graph=graph,
        question="比较 NVDA 和 AAPL",
        data_mode="mixed",
        as_of=as_of,
        thread_id="day38-case-5-multiple-resume",
    )
    print_result(
        title="CASE 5A - Multiple Targets",
        result=multiple_interrupted,
    )
    get_clarification(multiple_interrupted)
    require(
        multiple_interrupted["target_resolution"].status == "multiple",
        "NVDA + AAPL Target Resolution 不是 multiple",
    )
    require(
        multiple_interrupted["request"].company_ids == [],
        "多标的问题静默选择了第一只证券",
    )

    multiple_completed = await resume_case(
        graph=graph,
        answer="AAPL",
        context=multiple_context,
        graph_config=multiple_config,
    )
    print_result(
        title="CASE 5B - Multiple Resumed With AAPL",
        result=multiple_completed,
    )
    require("__interrupt__" not in multiple_completed, "AAPL 恢复后仍然 interrupt")
    require(
        multiple_completed["request"].question == "比较 NVDA 和 AAPL",
        "Multiple resume 改写了原始 question",
    )
    require(
        multiple_completed["request"].company_ids == ["AAPL"],
        "Multiple resume 没有写入 AAPL",
    )
    require(has_terminal_answer(multiple_completed), "Multiple resume 没有最终回答")

    # =====================================================
    # Case 6：无效 clarification 必须再次 interrupt
    # =====================================================

    invalid_interrupted, invalid_context, invalid_config = await run_case(
        graph=graph,
        question="Google 怎么看",
        data_mode="mixed",
        as_of=as_of,
        thread_id="day38-case-6-invalid-clarification",
    )
    get_clarification(invalid_interrupted)

    invalid_resumed = await resume_case(
        graph=graph,
        answer="就那个",
        context=invalid_context,
        graph_config=invalid_config,
    )
    print_result(
        title="CASE 6 - Invalid Clarification",
        result=invalid_resumed,
    )
    invalid_clarification = get_clarification(invalid_resumed)
    require(
        invalid_clarification["type"] == "target_clarification",
        "无效 clarification 没有再次请求补充标的",
    )
    require(
        invalid_resumed["request"].question == "Google 怎么看",
        "无效 clarification 改写了原始 question",
    )
    require(
        invalid_resumed["request"].company_ids == [],
        "无效 clarification 被当成了有效 ticker",
    )
    require(invalid_resumed["plan"] is None, "无效 clarification 后误进 Planner")
    require(not invalid_resumed["results"], "无效 clarification 后误进 Research")
    require(invalid_resumed["output"] is None, "无效 clarification 后误生成回答")

    print()
    print("Day38 LangGraph start / interrupt / resume verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
