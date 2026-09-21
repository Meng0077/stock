"""Day17：持久化索引增量更新的最小验收。

验证四件事：

1. 没有可复用索引时执行 full build。
2. 有历史索引时，只处理新增 filing 和新增 chunks。
3. exact snapshot 存在时直接复用。
4. historical retrieval 只搜索当前 snapshot 允许的 document versions。

运行：

    PYTHONPATH=backend/src \
    backend/.venv/bin/python \
    evals/verify_incremental_index.py
"""

from datetime import datetime, timezone
from unittest.mock import Mock, patch

import stock_agent.retrieval.indexing as indexing
import stock_agent.retrieval.knowledge as knowledge

from stock_agent.retrieval.schemas import (
    DEFAULT_INDEX_CONFIG,
    build_index_config_id,
)


COMPANY_ID = "NVDA"

AS_OF_1 = datetime(
    2026,
    9,
    10,
    tzinfo=timezone.utc,
)

AS_OF_HISTORICAL = datetime(
    2026,
    9,
    15,
    tzinfo=timezone.utc,
)

AS_OF_2 = datetime(
    2026,
    9,
    20,
    tzinfo=timezone.utc,
)

CONFIG_ID = build_index_config_id(
    DEFAULT_INDEX_CONFIG
)


BASE_MANIFEST = {
    "company_id": COMPANY_ID,
    "as_of": AS_OF_1,
    "index_config_id": CONFIG_ID,
    "document_versions": {
        "document-A": "hash-A",
        "document-B": "hash-B",
        "document-C": "hash-C",
    },
    "chunk_count": 6,
}


UPDATED_MANIFEST = {
    "company_id": COMPANY_ID,
    "as_of": AS_OF_2,
    "index_config_id": CONFIG_ID,
    "document_versions": {
        **BASE_MANIFEST["document_versions"],
        "document-D": "hash-D",
    },
    "chunk_count": 8,
}


HISTORICAL_MANIFEST = {
    "company_id": COMPANY_ID,
    "as_of": AS_OF_HISTORICAL,
    "index_config_id": CONFIG_ID,
    "document_versions": {
        "document-A": "hash-A",
        "document-B": "hash-B",
        "document-C": "hash-C",
    },
    "chunk_count": 6,
}


def build_filing(
    accession_number: str,
) -> Mock:
    return Mock(
        accession_number=accession_number
    )


def fail_if_called(*args, **kwargs):
    raise AssertionError(
        "this function should not be called"
    )


def verify_full_build() -> None:
    """没有 exact/base snapshot 时，应该 full build。"""

    engine = Mock()

    with (
        patch.object(
            indexing,
            "get_company_index",
            side_effect=[
                None,
                BASE_MANIFEST,
            ],
        ),
        patch.object(
            indexing,
            "get_latest_compatible_company_index",
            return_value=None,
        ),
        patch.object(
            indexing,
            "build_company_index",
        ) as build_mock,
    ):
        result = indexing.ensure_company_index(
            engine=engine,
            company_id=COMPANY_ID,
            as_of=AS_OF_1,
            config=DEFAULT_INDEX_CONFIG,
        )

    build_mock.assert_called_once_with(
        engine=engine,
        company_id=COMPANY_ID,
        as_of=AS_OF_1,
        config=DEFAULT_INDEX_CONFIG,
    )

    assert result == BASE_MANIFEST

    print("PASS full build")


def verify_incremental_update() -> None:
    """已有历史 snapshot 时，只处理新增 filing D。"""

    engine = Mock()

    filings = [
        build_filing("A"),
        build_filing("B"),
        build_filing("C"),
        build_filing("D"),
    ]

    new_chunks = [
        Mock(
            chunk_id="chunk-D-0",
            content="content-D-0",
        ),
        Mock(
            chunk_id="chunk-D-1",
            content="content-D-1",
        ),
    ]

    with (
        patch.object(
            indexing,
            "get_company_index",
            side_effect=[
                None,
                UPDATED_MANIFEST,
            ],
        ),
        patch.object(
            indexing,
            "get_latest_compatible_company_index",
            return_value=BASE_MANIFEST,
        ),
        patch.object(
            indexing,
            "get_recent_filings",
            return_value=filings,
        ),
        patch.object(
            indexing,
            "get_indexed_accession_numbers",
            return_value={
                "A",
                "B",
                "C",
            },
        ),
        patch.object(
            indexing,
            "process_new_filings",
            return_value=(
                {
                    "document-D": "hash-D",
                },
                new_chunks,
            ),
        ) as process_mock,
        patch.object(
            indexing,
            "embed_new_chunks",
        ) as embed_mock,
        patch.object(
            indexing,
            "save_company_index",
        ) as save_mock,
    ):
        result = indexing.ensure_company_index(
            engine=engine,
            company_id=COMPANY_ID,
            as_of=AS_OF_2,
            config=DEFAULT_INDEX_CONFIG,
        )

    # 只应该处理新增 filing D
    process_mock.assert_called_once()

    (
        processed_engine,
        processed_filings,
        processed_config,
    ) = process_mock.call_args.args

    assert processed_engine is engine
    assert processed_config == DEFAULT_INDEX_CONFIG

    assert [
        filing.accession_number
        for filing in processed_filings
    ] == ["D"]

    # 只应该 embedding D 新生成的 chunks
    embed_mock.assert_called_once_with(
        engine,
        new_chunks,
        DEFAULT_INDEX_CONFIG,
    )

    # 新 snapshot 必须包含旧 documents + D
    save_mock.assert_called_once()

    saved = save_mock.call_args.kwargs

    assert saved["document_versions"] == {
        "document-A": "hash-A",
        "document-B": "hash-B",
        "document-C": "hash-C",
        "document-D": "hash-D",
    }

    assert saved["chunk_count"] == 8
    assert saved["as_of"] == AS_OF_2

    assert result == UPDATED_MANIFEST

    print(
        "PASS incremental update "
        "processes only new filing/chunks"
    )


def verify_exact_reuse() -> None:
    """exact snapshot 已存在时，不允许进入 freshness 流程。"""

    engine = Mock()

    with (
        patch.object(
            indexing,
            "get_company_index",
            return_value=UPDATED_MANIFEST,
        ),
        patch.object(
            indexing,
            "get_latest_compatible_company_index",
            side_effect=fail_if_called,
        ),
        patch.object(
            indexing,
            "get_recent_filings",
            side_effect=fail_if_called,
        ),
        patch.object(
            indexing,
            "process_new_filings",
            side_effect=fail_if_called,
        ),
        patch.object(
            indexing,
            "embed_new_chunks",
            side_effect=fail_if_called,
        ),
    ):
        result = indexing.ensure_company_index(
            engine=engine,
            company_id=COMPANY_ID,
            as_of=AS_OF_2,
            config=DEFAULT_INDEX_CONFIG,
        )

    assert result == UPDATED_MANIFEST

    print("PASS exact snapshot reuse")


def verify_historical_retrieval() -> None:
    """历史查询必须只搜索 manifest 中允许的 documents。"""

    engine = Mock()

    query_embeddings = Mock()

    query_embeddings.embed_query.return_value = (
        [0.1]
        * DEFAULT_INDEX_CONFIG.embedding_dimension
    )

    def search_similar_chunks(**kwargs):
        document_versions = kwargs[
            "document_versions"
        ]

        # 09-18 才出现的 D
        # 不能出现在 09-15 historical snapshot
        assert (
            "document-D"
            not in document_versions
        )

        assert document_versions == (
            HISTORICAL_MANIFEST[
                "document_versions"
            ]
        )

        return [
            {
                "chunk_id": "chunk-A-0",
                "company_id": COMPANY_ID,
                "document_id": "document-A",
                "content": "historical content A",
            },
            {
                "chunk_id": "chunk-B-0",
                "company_id": COMPANY_ID,
                "document_id": "document-B",
                "content": "historical content B",
            },
        ]

    with (
        patch.object(
            knowledge,
            "ensure_company_index",
            return_value=HISTORICAL_MANIFEST,
        ),
        patch.object(
            knowledge,
            "build_embeddings",
            return_value=query_embeddings,
        ),
        patch.object(
            knowledge,
            "search_similar_chunks",
            side_effect=search_similar_chunks,
        ) as search_mock,
    ):
        results = knowledge.retrieve_knowledge(
            engine=engine,
            company_id=COMPANY_ID,
            question="What happened recently?",
            as_of=AS_OF_HISTORICAL,
            config=DEFAULT_INDEX_CONFIG,
            k=5,
        )

    search_mock.assert_called_once()

    assert results

    assert all(
        result["source"]
        in {
            "document-A",
            "document-B",
            "document-C",
        }
        for result in results
    )

    print(
        "PASS historical retrieval "
        "excludes future documents"
    )


def main() -> None:
    verify_full_build()

    verify_incremental_update()

    verify_exact_reuse()

    verify_historical_retrieval()

    print("PASS Day17")


if __name__ == "__main__":
    main()
