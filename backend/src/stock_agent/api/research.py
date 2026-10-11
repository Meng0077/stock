import asyncio
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command

from stock_agent.agents.context import ResearchContext
from stock_agent.agents.langgraph.graph import build_initial_state
from stock_agent.api.dependencies import (
    get_macro_builder_factory,
    get_market_provider_factory,
    get_research_graph,
)
from stock_agent.schemas.errors import make_public_error, map_error
from stock_agent.schemas.research import (
    ResearchInput,
    ResearchRequest,
    ResearchResumeInput,
    ResearchWorkflowResponse,
)

router = APIRouter()


def build_research_request(
    input: ResearchInput,
    *,
    company_id: str | None,
) -> ResearchRequest:
    return ResearchRequest(
        company_id=company_id,
        question=input.message,
        data_mode="mixed",
        as_of=datetime.now(timezone.utc),
    )


def build_graph_config(
    thread_id: str,
) -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,
        }
    }


@router.post("/api/research", response_model=ResearchWorkflowResponse)
async def research(
    body: ResearchInput,
    graph=Depends(get_research_graph),
    macro_builder_factory=Depends(get_macro_builder_factory),
    market_provider_factory=Depends(get_market_provider_factory),
):
    thread_id = str(uuid.uuid4())

    request = build_research_request(
        body,
        company_id=None,
    )
    context = ResearchContext(
        as_of=request.as_of,
        macro_builder_factory=macro_builder_factory,
        market_provider_factory=market_provider_factory,
        market_state="unknown",
    )

    try:
        result = await graph.ainvoke(
            build_initial_state(request),
            context=context,
            config=build_graph_config(thread_id),
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return ResearchWorkflowResponse(
            thread_id=thread_id,
            status="failed",
            error=make_public_error(map_error(error)).model_dump(),
        )

    interrupts = result.get("__interrupt__")

    if interrupts:
        return ResearchWorkflowResponse(
            thread_id=thread_id,
            status="needs_input",
            clarification=interrupts[0].value,
        )

    return ResearchWorkflowResponse(
        thread_id=thread_id,
        status="completed",
        result=result.get("output"),
    )


@router.post("/api/research/resume", response_model=ResearchWorkflowResponse)
async def resume_research(
    body: ResearchResumeInput,
    graph=Depends(get_research_graph),
    macro_builder_factory=Depends(get_macro_builder_factory),
    market_provider_factory=Depends(get_market_provider_factory),
):
    config = build_graph_config(body.thread_id)
    snapshot = await graph.aget_state(config)

    if not snapshot.values:
        raise HTTPException(
            status_code=404,
            detail="Research workflow does not exist",
        )
    request = snapshot.values["request"]

    context = ResearchContext(
        as_of=request.as_of,
        macro_builder_factory=macro_builder_factory,
        market_provider_factory=market_provider_factory,
        market_state="unknown",
    )

    try:
        result = await graph.ainvoke(
            Command(resume=body.answer),
            config=config,
            context=context,
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return ResearchWorkflowResponse(
            thread_id=body.thread_id,
            status="failed",
            error=make_public_error(map_error(error)).model_dump(),
        )

    interrupts = result.get("__interrupt__")

    if interrupts:
        return ResearchWorkflowResponse(
            thread_id=body.thread_id,
            status="needs_input",
            clarification=interrupts[0].value,
        )
    return ResearchWorkflowResponse(
        thread_id=body.thread_id,
        status="completed",
        result=result.get("output"),
    )
