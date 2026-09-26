"""Day24 真实模型、Macro Tool 和真实 Provider 端到端验收。"""

import asyncio
from datetime import datetime, timezone

from stock_agent.agents.langchain.langchain_agent import run_research
from stock_agent.api.dependencies import (
    get_langchain_agent,
    get_macro_builder_factory,
)
from stock_agent.schemas.research import ResearchRequest


async def main() -> None:
    request = ResearchRequest(
        company_id="NVDA",
        question=(
            "请使用宏观工具查询最近一次 CPI 发布，说明 Actual、Previous、"
            "Consensus 和 Surprise 的可用情况，并且只引用工具返回的证据。"
        ),
        data_mode="mixed",
        as_of=datetime.now(timezone.utc),
    )
    result = await run_research(
        agent=get_langchain_agent(),
        request=request,
        macro_builder_factory=get_macro_builder_factory(),
    )

    assert result["error"] is None, result["error"]
    assert result["output"] is not None

    macro_events = [
        event
        for event in result["events"]
        if event.get("tool") == "get_macro_snapshot"
    ]
    assert [event["type"] for event in macro_events] == [
        "tool_requested",
        "tool_succeeded",
    ]

    evidence_ids = {
        evidence_id
        for fact in result["output"].facts
        for evidence_id in fact.evidence_ids
    }
    assert any(
        evidence_id.startswith("macro:")
        for evidence_id in evidence_ids
    )

    print("status=", result["status"])
    print("macro_tool_events=", [event["type"] for event in macro_events])
    print("macro_evidence_ids=", sorted(evidence_ids))
    print("Day24 macro Agent verification passed.")


if __name__ == "__main__":
    asyncio.run(main())
