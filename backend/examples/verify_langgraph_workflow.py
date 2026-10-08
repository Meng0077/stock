"""Day36 LangGraph 真实 Live Smoke。

真实调用 DeepSeek、LangGraph、Longbridge 和 Macro Provider，
不提交交易订单。

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
) -> dict[str, Any]:
    request = ResearchRequest(
        company_id="NVDA",
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

    return await graph.ainvoke(
        build_initial_state(request),
        context=context,
    )


def print_result(*, title: str, result: dict[str, Any]) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)

    plan = result.get("plan")
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
    graph = build_research_graph(model)
    # 给真实 Provider 请求和 received_at 留出明确网络窗口。
    # MarketContext 仍然保持严格的 as_of 时间边界。
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)

    # =====================================================
    # Case 1：Quote only
    # =====================================================

    quote_result = await run_case(
        graph=graph,
        question="NVDA 现在多少钱？",
        data_mode="live",
        as_of=as_of,
    )
    print_result(title="CASE 1 - Quote", result=quote_result)

    quote_plan = quote_result["plan"]
    if not quote_plan.needs_quote:
        print("验收失败：Quote case 未规划 needs_quote。", file=sys.stderr)
        return 1
    if "quote" not in quote_result["results"]:
        print("验收失败：Quote case 没有 quote result。", file=sys.stderr)
        return 1
    if not has_terminal_answer(quote_result):
        print("验收失败：Quote case 没有形成终态回答。", file=sys.stderr)
        return 1

    # =====================================================
    # Case 2：Technical + Decision
    # =====================================================

    technical_result = await run_case(
        graph=graph,
        question="NVDA 当前走势怎么看，同时告诉我 RSI14。",
        data_mode="live",
        as_of=as_of,
    )
    print_result(
        title="CASE 2 - Technical + Decision",
        result=technical_result,
    )

    technical_plan = technical_result["plan"]
    if not technical_plan.needs_technical:
        print("验收失败：联合问题缺少 needs_technical。", file=sys.stderr)
        return 1
    if not technical_plan.needs_decision:
        print("验收失败：联合问题缺少 needs_decision。", file=sys.stderr)
        return 1

    technical_results = technical_result["results"]
    if (
        "technical" not in technical_results
        or "decision" not in technical_results
    ):
        print(
            "验收失败：Technical / Decision 结果不完整。",
            file=sys.stderr,
        )
        return 1

    technical = technical_results["technical"]
    if technical is None or technical.rsi14 is None:
        print("验收失败：RSI14 不可用。", file=sys.stderr)
        return 1
    if not has_terminal_answer(technical_result):
        print(
            "验收失败：Technical case 没有形成终态回答。",
            file=sys.stderr,
        )
        return 1

    # =====================================================
    # Case 3：CPI Market Reaction
    # =====================================================

    macro_result = await run_case(
        graph=graph,
        question="最近一次 CPI 后 NVDA 怎么走？",
        data_mode="mixed",
        as_of=as_of,
    )
    print_result(
        title="CASE 3 - CPI Market Reaction",
        result=macro_result,
    )

    macro_plan = macro_result["plan"]
    if not macro_plan.needs_macro:
        print("验收失败：CPI reaction 缺少 needs_macro。", file=sys.stderr)
        return 1
    if macro_plan.macro_release_type != "cpi":
        print("验收失败：CPI release_type 规划错误。", file=sys.stderr)
        return 1
    if not macro_plan.needs_macro_reaction:
        print("验收失败：CPI reaction 没有规划 reaction。", file=sys.stderr)
        return 1

    macro_results = macro_result["results"]
    if "macro_snapshot" not in macro_results:
        print("验收失败：没有 macro_snapshot。", file=sys.stderr)
        return 1
    if "macro_reaction" not in macro_results:
        print("验收失败：没有 macro_reaction。", file=sys.stderr)
        return 1
    if not has_terminal_answer(macro_result):
        print("验收失败：Macro case 没有形成终态回答。", file=sys.stderr)
        return 1

    print()
    print("Day36 LangGraph live workflow verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
