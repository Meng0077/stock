from dataclasses import dataclass
from datetime import datetime

from langchain_core.vectorstores import (
    InMemoryVectorStore,
)

from stock_agent.retrieval.schemas import (
    IndexConfig,
)


@dataclass
class CompanyIndexState:
    # 公司的索引
    company_id: str
    as_of: datetime


    # chunk / embedding 配置建立的
    config: IndexConfig
    # config 的稳定 fingerprint
    config_id: str

    # 当前索引里有哪些 document，以及各自 content_hash
    document_versions: dict[str, str]

    # 真正的 InMemoryVectorStore
    vector_store: InMemoryVectorStore

    # 当前索引一共放了多少 chunk
    chunk_count: int

IndexStateKey=tuple[str, datetime, str]

_COMPANY_INDEX_STATES: dict[IndexStateKey,CompanyIndexState] = {}

def build_index_state_key(company_id: str, as_of: datetime, config_id: str) -> IndexStateKey:
    return (company_id, as_of, config_id)

def get_company_index_state( company_id: str, as_of: datetime, config_id: str) -> CompanyIndexState | None:
    key = build_index_state_key(company_id, as_of, config_id)
    return _COMPANY_INDEX_STATES.get(key)


def get_latest_company_index_state(
    company_id: str,
    config_id: str,
    as_of: datetime | None = None,
) -> CompanyIndexState | None:
    matches = [
        state
        for state in _COMPANY_INDEX_STATES.values()
        if state.company_id == company_id and state.config_id == config_id
        and (as_of is None or state.as_of <= as_of)
    ]
    return max(matches, key=lambda state: state.as_of, default=None)


def save_company_index_state( state: CompanyIndexState ) ->  None:
    key = build_index_state_key(state.company_id, state.as_of, state.config_id)
    _COMPANY_INDEX_STATES[key] = state

def clear_company_index_states() -> None:
    _COMPANY_INDEX_STATES.clear()
