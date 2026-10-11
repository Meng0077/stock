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
from stock_agent.api.research_tasks import (
    ResearchTaskAlreadyRunningError,
    ResearchTaskCancelledError,
    cancel_research_task,
    run_research_task,
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
    thread_id = (
        str(body.thread_id)
        if body.thread_id is not None
        else str(uuid.uuid4())
    )

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
    config = build_graph_config(thread_id)
    snapshot = await graph.aget_state(config)

    if snapshot.values:
        raise HTTPException(
            status_code=409,
            detail=f"Research workflow {thread_id} already exists",
        )

    try:
        result = await run_research_task(
            thread_id,
            lambda: graph.ainvoke(
                build_initial_state(request),
                config=config,
                context=context,
            ),
        )
    except ResearchTaskCancelledError:
        return ResearchWorkflowResponse(thread_id=thread_id, status="cancelled")
    except ResearchTaskAlreadyRunningError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
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
        result = await run_research_task(
            body.thread_id,
            lambda: graph.ainvoke(
                Command(resume=body.answer),
                config=config,
                context=context,
            ),
        )
    except ResearchTaskCancelledError:
        return ResearchWorkflowResponse(thread_id=body.thread_id, status="cancelled")
    except ResearchTaskAlreadyRunningError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
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


@router.post("/api/research/{thread_id}/cancel")
async def cancel_research(thread_id: str):
    cancelled = cancel_research_task(thread_id)
    if not cancelled:
        raise HTTPException(
            status_code=404,
            detail=f"Research workflow {thread_id} is not running",
        )

    return {
        "thread_id": thread_id,
        "status": "cancelling",
    }


@router.post(
    "/api/research/{thread_id}/continue",
    response_model=ResearchWorkflowResponse,
)
async def continue_research(
    thread_id: str,
    graph=Depends(get_research_graph),
    macro_builder_factory=Depends(get_macro_builder_factory),
    market_provider_factory=Depends(get_market_provider_factory),
):
    config = build_graph_config(thread_id)
    snapshot = await graph.aget_state(config)

    if not snapshot.values:
        raise HTTPException(
            status_code=404,
            detail="Research workflow does not exist",
        )

    if snapshot.interrupts:
        raise HTTPException(
            status_code=409,
            detail="Research workflow is waiting for user input",
        )

    if not snapshot.next:
        raise HTTPException(
            status_code=409,
            detail=(
                "Research workflow "
                "has already completed"
            ),
        )

    request = snapshot.values["request"]
    context = ResearchContext(
        as_of=request.as_of,
        macro_builder_factory=macro_builder_factory,
        market_provider_factory=market_provider_factory,
        market_state="unknown",
    )

    try:
        result = await run_research_task(
            thread_id,
            lambda: graph.ainvoke(
                None,
                config=config,
                context=context,
            ),
        )
    except ResearchTaskCancelledError:
        return ResearchWorkflowResponse(
            thread_id=thread_id,
            status="cancelled",
        )

    except ResearchTaskAlreadyRunningError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    except asyncio.CancelledError:
        raise

    except Exception as error:
        return ResearchWorkflowResponse(
            thread_id=thread_id,
            status="failed",
            error=make_public_error(
                map_error(error)
            ).model_dump(),
        )

    if result.get("__interrupt__"):
        return ResearchWorkflowResponse(
            thread_id=thread_id,
            status="needs_input",
            clarification=result["__interrupt__"][0].value,
        )

    return ResearchWorkflowResponse(
        thread_id=thread_id,
        status="completed",
        result=result.get("output"),
    )
