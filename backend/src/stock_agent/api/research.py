from datetime import datetime, timezone
import re

from stock_agent.api.dependencies import get_langchain_agent
from stock_agent.agents.langchain.langchain_agent import run_research
from stock_agent.schemas.research import ResearchInput, ResearchRequest, ResearchResponse
from fastapi import APIRouter, Depends, HTTPException

from typing import Annotated

router = APIRouter()

def extract_company_id(message: str) -> str:
    match = re.search(r"\b[A-Z]{1,5}\b", message)

    if not match:
        raise ValueError("没有识别到股票代码")

    return match.group()
    
def build_research_request(
    input: ResearchInput,
) -> ResearchRequest:
    company_id = extract_company_id(input.message)

    return ResearchRequest(
        company_id=company_id,
        question=input.message,
        data_mode="fixture",
        as_of=datetime.now(timezone.utc),
    )

@router.post("/api/research", response_model=ResearchResponse)
async def research(body: ResearchInput, agent: Annotated[object, Depends(get_langchain_agent)]):
    try:
        request = build_research_request(body)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )
    record = await run_research(agent=agent, request=request)
    return ResearchResponse(
        run_id=str(record["run_id"]),
        status=record["status"],
        result=record["output"],
        error=record["error"],
    )