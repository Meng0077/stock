from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine
from stock_agent.retrieval.schemas import DEFAULT_INDEX_CONFIG, IndexConfig


@dataclass(frozen=True)
class ResearchContext:
    as_of: datetime
    engine: Engine | None = None
    index_config: IndexConfig = DEFAULT_INDEX_CONFIG
