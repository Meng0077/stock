import asyncio
from datetime import datetime, timezone
from pathlib import Path

from langchain_deepseek import ChatDeepSeek
from langchain.agents.structured_output import ToolStrategy

from stock_agent.schemas.research_output import ResearchOutput
from stock_agent.agents.langchain.langchain_agent import (
    build_langchain_agent,
    run_research,
)
from stock_agent.llm_client import get_llm_config
from stock_agent.schemas.research import ResearchRequest


ROOT = Path(__file__).resolve().parents[1]

CASES = [
    {
        "name": "quote_only",
        "company_id": "NVDA",
        "expected_status": "completed",
        "question": "NVDA 当前教学模拟报价是多少？",
        "required_tools": {
            "get_quote",
        },
        "required_evidence_prefixes": {
            "E-",
        },
    },
    {
        "name": "knowledge_only",
        "company_id": "NVDA",
        "expected_status": "completed",
        "question": "NVDA 的数据中心业务主要受到什么需求推动？",
        "required_tools": {
            "retrieve_knowledge",
        },
        "required_evidence_prefixes": {
            "rag:",
        },
    },
    {
        "name": "quote_and_knowledge",
        "company_id": "NVDA",
        "expected_status": "completed",
        "question": (
            "NVDA 当前教学模拟报价是多少？"
            "它的数据中心业务主要受到什么需求推动？"
        ),
        "required_tools": {
            "get_quote",
            "retrieve_knowledge",
        },
        "required_evidence_prefixes": {
            "E-",
            "rag:",
        },
    },
    {
        "name": "missing_documents",
        "company_id": "TSLA",
        "expected_status": "insufficient_information",
        "question": "TSLA 的主要业务是什么？请依据本地公司文档回答。",
        "required_tools": {"retrieve_knowledge"},
        "required_evidence_prefixes": set(),
    },
]


def collect_called_tools(record) -> set[str]:
    return {
        event["tool"]
        for event in record["events"]
        if event["type"] == "tool_requested"
    }

def collect_used_evidence_ids(record) -> set[str]:
    output = record["output"]

    if output is None:
        return set()

    claims = (
        output.facts
        + output.inferences
    )

    return {
        evidence_id
        for claim in claims
        for evidence_id in claim.evidence_ids
    }

async def verify_case(
    agent,
    case,
):

    request = ResearchRequest(
        company_id=case["company_id"],
        question=case["question"],
        data_mode="fixture",
        as_of=datetime.now(timezone.utc),
    )
    record = await run_research(agent, request)


    if record["status"] != case["expected_status"]:
        print(
            "FAIL",
            case["name"],
            "status:", record["status"],
            record["error"],
        )
        return False

    called_tools = collect_called_tools(
        record
    )

    if not case["required_tools"] <= called_tools:
        print(
            "FAIL",
            case["name"],
            "tools:",
            called_tools,
        )
        return False

    evidence_ids = collect_used_evidence_ids(
        record
    )

    for prefix in case[
        "required_evidence_prefixes"
    ]:
        if not any(
            evidence_id.startswith(prefix)
            for evidence_id in evidence_ids
        ):
            print(
                "FAIL",
                case["name"],
                "evidence:",
                evidence_ids,
            )
            return False

    print(
        "PASS",
        case["name"],
    )

    return True




async def main():
    config = get_llm_config(ROOT / 'backend' / ".env")
    model = ChatDeepSeek(
        model=config.model,
        api_key=config.api_key,
        temperature=0,
        timeout=60,
        max_retries=0,
        extra_body={"thinking": {"type": "disabled"}},
    )
    agent = build_langchain_agent(model, response_format=ToolStrategy(ResearchOutput))
    results = []
    for case in CASES:
        result =  await verify_case(agent=agent, case=case)
        results.append(result)

    if not all(results):
        raise SystemExit(1)

    # request = ResearchRequest(
    #     company_id="NVDA",
    #     question=(
    #         "NVDA 当前报价怎么样，同时它的数据中心业务主要靠什么？"
    #         # "NVDA 的数据中心业务主要受到什么需求推动？"

    #     ),
    #     data_mode="fixture",
    #     as_of=datetime.now(timezone.utc),
    # )

    # result = await invoke_langchain_agent(agent, request)
    # result = await run_research(agent, request,)

    # print(result)


if __name__ == "__main__":
    asyncio.run(main())
