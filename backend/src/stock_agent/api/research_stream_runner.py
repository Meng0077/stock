from typing import Any

from stock_agent.agents.context import ResearchContext
from stock_agent.api.research_event_store import ResearchEventStore
from stock_agent.company.resolver import TargetResolution
from stock_agent.schemas.research_events import (
    ResearchExecutionType,
    ResearchStage,
)


NODE_STAGE_MAP: dict[str, ResearchStage] = {
    "resolve_target": "target_resolution",
    "planner": "planning",
    "research": "research",
    "checker": "checking",
    "answer": "answering",
}


def is_task_started(chunk: dict[str, Any]) -> bool:
    return "input" in chunk


def get_task_stage(chunk: object) -> ResearchStage | None:
    if not isinstance(chunk, dict):
        return None
    if not is_task_started(chunk):
        return None
    name = chunk["name"]
    if not isinstance(name, str):
        return None
    return NODE_STAGE_MAP.get(name)


def get_node_update(chunk: object) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(chunk, dict):
        return None

    if len(chunk) != 1:
        return None

    name, update = next(iter(chunk.items()))
    if not isinstance(name, str):
        return None
    if not isinstance(update, dict):
        return None

    return name, update


def build_target_resolution_event_data(
    update: dict[str, object],
) -> dict[str, object]:
    resolution: object = update.get("target_resolution")

    if not isinstance(resolution, TargetResolution):
        raise ValueError("target_resolution update is missing")

    ambiguous_targets = [
        {
            "mention": target.mention,
            "candidates": list(target.candidates),
        }
        for target in resolution.ambiguous_targets
    ]

    return {
        "status": resolution.status,
        "company_ids": list(resolution.resolved_targets),
        "ambiguous_targets": ambiguous_targets,
        "unresolved_mentions": list(resolution.unresolved_mentions),
    }


async def handle_task_chunk(
    *,
    thread_id: str,
    chunk: object,
    event_store: ResearchEventStore,
) -> None:
    if not isinstance(chunk, dict):
        return None

    stage = get_task_stage(chunk)
    if stage is None:
        return
    await event_store.publish(thread_id, "stage_changed", {"stage": stage})


async def handle_update_chunk(
    *,
    thread_id: str,
    chunk: object,
    event_store: ResearchEventStore,
) -> None:
    node_update = get_node_update(chunk)
    if node_update is None:
        return
    name, update = node_update

    if name != "resolve_target":
        return
    data = build_target_resolution_event_data(update)
    await event_store.publish(thread_id, "target_resolution", data)


def get_answer_delta(chunk: object) -> str | None:
    if not isinstance(chunk, tuple) or len(chunk) != 2:
        return None
    message, metadata = chunk
    if not isinstance(metadata, dict):
        return None

    if metadata.get("langgraph_node") != "answer":
        return None

    content = getattr(message, "content", None)

    if not isinstance(content, str):
        return None

    return content


async def handle_message_chunk(
    *,
    thread_id: str,
    chunk: object,
    event_store: ResearchEventStore,
) -> None:
    text = get_answer_delta(chunk)
    if text is None:
        return

    await event_store.publish(thread_id, "answer_delta", {"text": text})


async def handle_graph_stream_chunk(
    *,
    thread_id: str,
    mode: str,
    chunk: object,
    event_store: ResearchEventStore,
) -> None:
    if mode == "tasks":
        await handle_task_chunk(
            thread_id=thread_id,
            chunk=chunk,
            event_store=event_store,
        )
    elif mode == "updates":
        await handle_update_chunk(
            thread_id=thread_id,
            chunk=chunk,
            event_store=event_store,
        )
    elif mode == "messages":
        await handle_message_chunk(
            thread_id=thread_id,
            chunk=chunk,
            event_store=event_store,
        )


async def run_research_stream(
    *,
    graph,
    graph_input: object,
    thread_id: str,
    execution: ResearchExecutionType,
    context: ResearchContext,
    config: dict[str, Any],
    event_store: ResearchEventStore,
):
    """
    执行一次 Research Graph，并把运行过程发布为 ResearchEvent。

    stream chunk 只用于过程事件；
    最终结果以 LangGraph checkpoint 为准。
    """
    await event_store.publish(thread_id, "workflow_started", {"execution": execution})

    async for mode, chunk in graph.astream(
        graph_input,
        context=context,
        config=config,
        stream_mode=["tasks", "updates", "messages"],
    ):
        await handle_graph_stream_chunk(
            thread_id=thread_id,
            mode=mode,
            chunk=chunk,
            event_store=event_store,
        )

    snapshot = await graph.aget_state(config)
    if snapshot.interrupts:
        await event_store.publish(thread_id, "needs_input", snapshot.interrupts[0].value)

        return snapshot

    output = snapshot.values.get("output")
    if not isinstance(output, str):
        raise RuntimeError("research workflow completed without answer output")

    await event_store.publish(thread_id, "completed", {"result": output})
    return snapshot
