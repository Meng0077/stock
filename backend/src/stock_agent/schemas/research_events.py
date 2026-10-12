from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ResearchEventType = Literal[
    "workflow_started",
    "stage_changed",
    "target_resolution",
    "answer_delta",
    "needs_input",
    "completed",
    "failed",
    "cancelled",
]


ResearchStage = Literal[
    "target_resolution",
    "planning",
    "research",
    "checking",
    "answering",
]

ResearchExecutionType = Literal[
    "start",
    "resume",
    "continue",
]


class ResearchEvent(BaseModel):
    """
    一次 Research Workflow 的可重放流式事件。

    event_id 在同一个 thread_id 内单调递增，
    用于 SSE Last-Event-ID 短线重连。
    """

    event_id: int = Field(ge=1)
    thread_id: str
    type: ResearchEventType
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
