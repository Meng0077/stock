from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import httpx

from sqlalchemy import Engine
from stock_agent.documents.sec_http import SEC_CLIENT
from stock_agent.macro.builder import MacroSnapshotBuilder
from stock_agent.retrieval.schemas import DEFAULT_INDEX_CONFIG, IndexConfig


@dataclass(frozen=True)
class ResearchContext:
    as_of: datetime
    engine: Engine | None = None
    index_config: IndexConfig = DEFAULT_INDEX_CONFIG
    sec_client: httpx.Client = SEC_CLIENT
    macro_builder_factory: Callable[[], MacroSnapshotBuilder] | None = None
