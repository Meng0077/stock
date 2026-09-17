
import asyncio
import json
from pathlib import Path

from langchain.agents.structured_output import ToolStrategy
from langchain_deepseek import ChatDeepSeek
# from langchain.agents.middleware.model_call_limit import (
#     ModelCallLimitExceededError
# )
# from langchain.agents.middleware.tool_call_limit import (
#     ToolCallLimitExceededError
# )

from stock_agent.agents.langchain.langchain_agent import run_research
from stock_agent.agents.structured_output import collect_evidence_ids, validate_evidence
from stock_agent.schemas.research_output import ResearchOutput
from stock_agent.agents.langchain.langchain_agent import build_langchain_agent, invoke_langchain_agent
from stock_agent.llm_client import get_llm_config
from stock_agent.schemas.research import ResearchRequest



ROOT=Path(__file__).resolve().parents[1]
MODEL_TIMEOUT_SECONDS = 30

async def main():
    request = ResearchRequest(
        company_id="NVDA",
        question="NVDA 的数据中心业务主要靠什么",
        data_mode="fixture",
        as_of="2026-09-15T16:00:00+08:00",
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
    # 使用工具调用生成结构化结果，避免接口不支持原生 response_format。
    agent = build_langchain_agent(model, response_format=ToolStrategy(ResearchOutput))
    result = await run_research(agent, request)
    if result["output"] is not None:
        result["output"] = result["output"].model_dump(mode="json")
    print(json.dumps(result, ensure_ascii=False, indent=2))





if __name__ == "__main__":
    asyncio.run(main())
