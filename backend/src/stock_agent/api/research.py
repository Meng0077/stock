import asyncio
from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command

from stock_agent.agents.context import ResearchContext
from stock_agent.agents.langgraph.graph import build_initial_state
from stock_agent.api.dependencies import (
    get_macro_builder_factory,
    get_market_provider_factory,
    get_research_event_store,
    get_research_graph,
)
from stock_agent.api.research_event_store import ResearchEventStore
from stock_agent.api.research_stream_runner import run_research_stream
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
from stock_agent.schemas.research_events import ResearchExecutionType

router = APIRouter()


def build_research_request(input: ResearchInput) -> ResearchRequest:
    return ResearchRequest(
        question=input.message,
        data_mode="mixed",
        as_of=datetime.now(timezone.utc),
    )


def build_graph_config(thread_id: str) -> dict:
    return {
        "configurable": {
            "thread_id": thread_id,
        }
    }


async def execute_research_workflow(
    *,
    thread_id: str,
    graph,
    graph_input: object,
    execution: ResearchExecutionType,
    context: ResearchContext,
    config: dict[str, Any],
    event_store: ResearchEventStore,
) -> ResearchWorkflowResponse:
    """
    执行一次 Research Workflow。

    start / resume / continue 共用这一层；
    Task 生命周期、流式 Graph 和 API 状态
    在这里完成统一编排。
    """
    try:
        snapshot = await run_research_task(
            thread_id,
            lambda: run_research_stream(
                graph=graph,
                graph_input=graph_input,
                thread_id=thread_id,
                execution=execution,
                context=context,
                config=config,
                event_store=event_store,
            ),
        )
    except ResearchTaskCancelledError:
        await event_store.publish(thread_id, "cancelled")
        return ResearchWorkflowResponse(
            thread_id=thread_id,
            status="cancelled",
        )
    except ResearchTaskAlreadyRunningError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except asyncio.CancelledError:
        raise
    except Exception as error:
        public_error = make_public_error(map_error(error))
        await event_store.publish(thread_id, "failed", {"error": public_error.model_dump()})
        return ResearchWorkflowResponse(
            thread_id=thread_id,
            status="failed",
            error=public_error.model_dump(),
        )
    if snapshot.interrupts:
        return ResearchWorkflowResponse(
            thread_id=thread_id,
            status="needs_input",
            clarification=snapshot.interrupts[0].value,
        )

    return ResearchWorkflowResponse(
        thread_id=thread_id,
        status="completed",
        result=snapshot.values["output"],
    )


@router.post("/api/research", response_model=ResearchWorkflowResponse)
async def research(
    body: ResearchInput,
    graph=Depends(get_research_graph),
    macro_builder_factory=Depends(get_macro_builder_factory),
    market_provider_factory=Depends(get_market_provider_factory),
    event_store=Depends(get_research_event_store),
):
    thread_id = str(body.thread_id) if body.thread_id is not None else str(uuid.uuid4())

    request = build_research_request(body)
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
    return await execute_research_workflow(
        thread_id=thread_id,
        graph=graph,
        graph_input=build_initial_state(request),
        execution="start",
        context=context,
        config=config,
        event_store=event_store,
    )


@router.post("/api/research/resume", response_model=ResearchWorkflowResponse)
async def resume_research(
    body: ResearchResumeInput,
    graph=Depends(get_research_graph),
    macro_builder_factory=Depends(get_macro_builder_factory),
    market_provider_factory=Depends(get_market_provider_factory),
    event_store=Depends(get_research_event_store),
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

    return await execute_research_workflow(
        thread_id=body.thread_id,
        graph=graph,
        graph_input=Command(resume=body.answer),
        execution="resume",
        context=context,
        config=config,
        event_store=event_store,
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
    event_store=Depends(get_research_event_store),
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
            detail="Research workflow has already completed",
        )

    request = snapshot.values["request"]
    context = ResearchContext(
        as_of=request.as_of,
        macro_builder_factory=macro_builder_factory,
        market_provider_factory=market_provider_factory,
        market_state="unknown",
    )

    return await execute_research_workflow(
        thread_id=thread_id,
        graph=graph,
        graph_input=None,
        execution="continue",
        context=context,
        config=config,
        event_store=event_store,
    )
