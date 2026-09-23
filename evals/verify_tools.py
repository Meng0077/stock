"""Day18：验证 Agent 组合 Financial 与 Knowledge evidence。"""

import asyncio
from datetime import datetime
from pathlib import Path

from langchain.agents.structured_output import ToolStrategy
from langchain_deepseek import ChatDeepSeek

from stock_agent.agents.langchain.langchain_agent import (
    build_langchain_agent,
    run_research,
)
from stock_agent.llm_client import get_llm_config
from stock_agent.schemas.research import ResearchRequest
from stock_agent.schemas.research_output import ResearchOutput


ROOT = Path(__file__).resolve().parents[1]
MODEL_TIMEOUT_SECONDS = 300


async def verify_financial_and_knowledge_case() -> None:
    request = ResearchRequest(
        company_id="NVDA",
        question=(
            "NVDA 最近季度净利润是多少？"
            "管理层如何解释最近的业绩变化？"
        ),
        data_mode="mixed",
        as_of=datetime.fromisoformat(
            "2026-09-22T16:00:00+08:00"
        ),
    )

    config = get_llm_config(ROOT / "backend" / ".env")
    model = ChatDeepSeek(
        model=config.model,
        api_key=config.api_key,
        temperature=0,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=0,
        extra_body={"thinking": {"type": "disabled"}},
    )
    agent = build_langchain_agent(
        model,
        response_format=ToolStrategy(ResearchOutput),
    )

    result = await run_research(agent, request)
    assert result["status"] == "completed", result
    assert result["error"] is None

    requested_tools = {
        event["tool"]
        for event in result["events"]
        if event["type"] == "tool_requested"
    }
    assert "get_financial_facts" in requested_tools
    assert "retrieve_knowledge" in requested_tools

    output = result["output"]
    cited_ids = {
        evidence_id
        for claim in output.facts + output.inferences
        for evidence_id in claim.evidence_ids
    }
    assert any(
        evidence_id.startswith("financial:")
        for evidence_id in cited_ids
    )
    assert any(
        evidence_id.startswith("rag:")
        for evidence_id in cited_ids
    )
    assert output.data_mode == "historical"

    print(output.model_dump_json(indent=2))
    print("Day18 financial + knowledge verification passed.")


if __name__ == "__main__":
    asyncio.run(verify_financial_and_knowledge_case())
