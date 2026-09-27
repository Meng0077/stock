"""Day25 真实长桥行情与数据质量 Tool 验收。"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from langchain.tools import ToolRuntime

from stock_agent.agents.context import ResearchContext
from stock_agent.agents.langchain.langchain_tools import (
    get_technical_analysis_tool,
)
from stock_agent.market.longbridge.config_factory import (
    build_longbridge_market_provider,
)


ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    load_dotenv(ROOT / "backend" / ".env", override=False)
    as_of = datetime.now(timezone.utc) + timedelta(seconds=5)
    runtime = ToolRuntime(
        state={},
        context=ResearchContext(
            as_of=as_of,
            market_provider_factory=build_longbridge_market_provider,
            market_state="unknown",
        ),
        config={},
        stream_writer=lambda _: None,
        tool_call_id="verify-day25",
        store=None,
    )

    result = await get_technical_analysis_tool.coroutine(
        company_id="NVDA",
        runtime=runtime,
    )

    quality_results = {
        item["data_kind"]: item
        for item in result["quality"]["results"]
    }
    assert set(quality_results) == {"quote", "bars"}
    assert result["technical"] is not None
    assert result["quality"]["source_warnings"] == []

    print("symbol=", result["symbol"])
    print("quality_status=", result["quality"]["overall_status"])
    print("quote_status=", quality_results["quote"]["status"])
    print("bars_status=", quality_results["bars"]["status"])
    print("technical_evidence=", result["technical"]["evidence_id"])
    print("Day25 quality verification passed.")


if __name__ == "__main__":
    asyncio.run(main())
