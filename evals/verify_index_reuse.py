from datetime import datetime, timezone
from unittest.mock import Mock, patch

from stock_agent.retrieval.indexing import ensure_company_index
from stock_agent.retrieval.schemas import (
    DEFAULT_INDEX_CONFIG,
    IndexConfig,
    build_index_config_id,
)


class FakeIndexStorage:
    def __init__(self) -> None:
        self.indexes = []
        self.build_count = 0

    def get_exact(self, engine, company_id, as_of, index_config_id):
        return next((
            index
            for index in self.indexes
            if index["company_id"] == company_id
            and index["as_of"] == as_of
            and index["index_config_id"] == index_config_id
        ), None)

    def get_latest(self, engine, company_id, as_of, index_config_id):
        matches = [
            index
            for index in self.indexes
            if index["company_id"] == company_id
            and index["as_of"] < as_of
            and index["index_config_id"] == index_config_id
        ]
        return max(matches, key=lambda index: index["as_of"], default=None)

    def build(self, engine, company_id, as_of, config):
        self.build_count += 1
        self.indexes.append({
            "company_id": company_id,
            "as_of": as_of,
            "index_config_id": build_index_config_id(config),
            "document_versions": {"document-1": "content-hash-1"},
            "chunk_count": 42,
        })

    def save(
        self,
        engine,
        company_id,
        as_of,
        index_config_id,
        document_versions,
        chunk_count,
    ):
        self.indexes.append({
            "company_id": company_id,
            "as_of": as_of,
            "index_config_id": index_config_id,
            "document_versions": document_versions,
            "chunk_count": chunk_count,
        })


def ensure_with_fake_storage(
    storage: FakeIndexStorage,
    engine,
    company_id: str,
    as_of: datetime,
    config: IndexConfig = DEFAULT_INDEX_CONFIG,
):
    with (
        patch(
            "stock_agent.retrieval.indexing.get_company_index",
            side_effect=storage.get_exact,
        ),
        patch(
            "stock_agent.retrieval.indexing.get_latest_compatible_company_index",
            side_effect=storage.get_latest,
        ),
        patch(
            "stock_agent.retrieval.indexing.build_company_index",
            side_effect=storage.build,
        ),
        patch(
            "stock_agent.retrieval.indexing.get_indexed_accession_numbers",
            return_value={"accession-1"},
        ),
        patch(
            "stock_agent.retrieval.indexing.get_recent_filings",
            return_value=[Mock(accession_number="accession-1")],
        ),
        patch(
            "stock_agent.retrieval.indexing.save_company_index",
            side_effect=storage.save,
        ),
    ):
        return ensure_company_index(
            company_id=company_id,
            as_of=as_of,
            config=config,
            engine=engine,
        )


def verify_same_index_is_reused():
    storage = FakeIndexStorage()
    engine = Mock()
    as_of = datetime(2026, 9, 19, tzinfo=timezone.utc)

    first = ensure_with_fake_storage(storage, engine, "NVDA", as_of)
    second = ensure_with_fake_storage(storage, engine, "NVDA", as_of)

    assert first is second
    assert storage.build_count == 1
    print("PASS same index reused")


def verify_config_change_rebuilds():
    storage = FakeIndexStorage()
    engine = Mock()
    as_of = datetime(2026, 9, 19, tzinfo=timezone.utc)
    another_config = IndexConfig(
        chunk_size=1200,
        chunk_overlap=100,
        embedding_model=DEFAULT_INDEX_CONFIG.embedding_model,
    )

    first = ensure_with_fake_storage(
        storage,
        engine,
        "NVDA",
        as_of,
        DEFAULT_INDEX_CONFIG,
    )
    second = ensure_with_fake_storage(
        storage,
        engine,
        "NVDA",
        as_of,
        another_config,
    )

    assert first is not second
    assert storage.build_count == 2
    print("PASS config change rebuilds")


def verify_later_as_of_creates_snapshot_without_rebuild():
    storage = FakeIndexStorage()
    engine = Mock()
    first_as_of = datetime(2026, 9, 18, tzinfo=timezone.utc)
    second_as_of = datetime(2026, 9, 19, tzinfo=timezone.utc)

    first = ensure_with_fake_storage(storage, engine, "NVDA", first_as_of)
    second = ensure_with_fake_storage(storage, engine, "NVDA", second_as_of)

    assert first is not second
    assert first["document_versions"] == second["document_versions"]
    assert storage.build_count == 1
    assert len(storage.indexes) == 2
    print("PASS later as_of creates snapshot without rebuild")


def verify_earlier_as_of_rebuilds():
    storage = FakeIndexStorage()
    engine = Mock()
    future_as_of = datetime(2026, 9, 19, tzinfo=timezone.utc)
    historical_as_of = datetime(2026, 9, 18, tzinfo=timezone.utc)

    future = ensure_with_fake_storage(storage, engine, "NVDA", future_as_of)
    historical = ensure_with_fake_storage(
        storage,
        engine,
        "NVDA",
        historical_as_of,
    )

    assert future is not historical
    assert storage.build_count == 2
    print("PASS earlier as_of rebuilds")


def main():
    verify_same_index_is_reused()
    verify_config_change_rebuilds()
    verify_later_as_of_creates_snapshot_without_rebuild()
    verify_earlier_as_of_rebuilds()


if __name__ == "__main__":
    main()
