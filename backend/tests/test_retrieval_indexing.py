from datetime import date, datetime, timezone
from unittest.mock import MagicMock, Mock

import pytest

from stock_agent.documents.schemas import (
    SEC_HTML_PARSER_VERSION,
    FilingBlock,
    FilingDocument,
)
from stock_agent.retrieval import indexing
from stock_agent.retrieval import knowledge
from stock_agent.retrieval.chunking import build_evidence_id, split_filing_document
from stock_agent.retrieval.index_state import (
    clear_company_index_states,
)
from stock_agent.retrieval.schemas import (
    DEFAULT_INDEX_CONFIG,
    IndexConfig,
    build_index_config_id,
)
from stock_agent.storage.embeddings import (
    save_chunk_embeddings,
    search_similar_chunks,
)
from stock_agent.storage.indexes import get_company_index


def test_split_filing_document_returns_traceable_chunks():
    content = "Alpha beta\n\nGamma delta"
    document = FilingDocument(
        document_id="sec:1:accession:report.htm",
        company_id="NVDA",
        cik="0000000001",
        form="10-Q",
        filing_date=date(2026, 9, 1),
        accepted_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        accession_number="accession",
        document_name="report.htm",
        document_type="10-Q",
        is_primary=True,
        source_url="https://example.com/report.htm",
        content=content,
        content_hash="content-hash",
        blocks=[
            FilingBlock(
                block_id="block-1",
                document_id="sec:1:accession:report.htm",
                block_type="text",
                text="Alpha beta",
                start_char=0,
                end_char=10,
                source_xpath="/html/body/p[1]",
            ),
            FilingBlock(
                block_id="block-2",
                document_id="sec:1:accession:report.htm",
                block_type="text",
                text="Gamma delta",
                start_char=12,
                end_char=23,
                source_xpath="/html/body/p[2]",
            ),
        ],
    )
    config = IndexConfig(
        chunk_size=14,
        chunk_overlap=3,
        embedding_model="test-model",
    )

    chunks = split_filing_document(document, config)

    assert chunks
    langchain_document = indexing.to_langchain_document(chunks[0])
    assert langchain_document.metadata["evidence_id"] == build_evidence_id(
        chunks[0].chunk_id
    )
    assert chunks[-1].end_char == len(content)
    assert all(chunk.company_id == "NVDA" for chunk in chunks)
    assert all(chunk.source_url == document.source_url for chunk in chunks)
    assert all(content[chunk.start_char:chunk.end_char] == chunk.content for chunk in chunks)
    assert {block_id for chunk in chunks for block_id in chunk.source_block_ids} == {
        "block-1",
        "block-2",
    }
    assert {xpath for chunk in chunks for xpath in chunk.source_xpaths} == {
        "/html/body/p[1]",
        "/html/body/p[2]",
    }


@pytest.mark.parametrize(
    "update",
    [
        {"parser_version": "sec-html-v2"},
        {"embedding_revision": "revision-2"},
        {"embedding_dimension": 1024},
    ],
)
def test_index_metadata_changes_index_identity(update):
    changed = DEFAULT_INDEX_CONFIG.model_copy(update=update)
    assert DEFAULT_INDEX_CONFIG.parser_version == SEC_HTML_PARSER_VERSION
    assert build_index_config_id(changed) != build_index_config_id(DEFAULT_INDEX_CONFIG)


def test_build_company_index_persists_vectors_and_completion_marker(monkeypatch):
    clear_company_index_states()
    document = FilingDocument(
        document_id="sec:1:accession:report.htm",
        company_id="NVDA",
        cik="0000000001",
        form="10-Q",
        filing_date=date(2026, 9, 1),
        accepted_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        accession_number="accession",
        document_name="report.htm",
        document_type="10-Q",
        is_primary=True,
        source_url="https://example.com/report.htm",
        content="Alpha beta",
        content_hash="content-hash",
        blocks=[
            FilingBlock(
                block_id="block-1",
                document_id="sec:1:accession:report.htm",
                block_type="text",
                text="Alpha beta",
                start_char=0,
                end_char=10,
                source_xpath="/html/body/p[1]",
            ),
        ],
    )
    calls = []
    captured = {}

    monkeypatch.setattr(indexing, "create_database_tables", lambda engine: None)
    monkeypatch.setattr(indexing, "get_recent_filings", lambda *args, **kwargs: [object()])
    monkeypatch.setattr(
        indexing,
        "load_relevant_filing_documents",
        lambda filing: [document],
    )
    monkeypatch.setattr(
        indexing,
        "save_filing_document",
        lambda engine, document: calls.append("document"),
    )
    monkeypatch.setattr(
        indexing,
        "save_filing_blocks",
        lambda engine, document: calls.append("blocks"),
    )
    monkeypatch.setattr(
        indexing,
        "save_document_chunks",
        lambda engine, chunks, config: calls.append("chunks"),
    )

    def fake_vector_store(chunks, config):
        return Mock(
            store={
                chunk.chunk_id: {"vector": [float(chunk.chunk_index)]}
                for chunk in chunks
            },
        )

    def fake_save_embeddings(engine, chunks, vectors, config, index_config_id):
        calls.append("embeddings")
        captured["vectors"] = vectors

    def fake_save_index(**kwargs):
        calls.append("index")
        captured["index"] = kwargs

    monkeypatch.setattr(indexing, "build_company_vector_store", fake_vector_store)
    monkeypatch.setattr(indexing, "save_chunk_embeddings", fake_save_embeddings)
    monkeypatch.setattr(indexing, "save_company_index", fake_save_index)

    as_of = datetime(2026, 9, 19, tzinfo=timezone.utc)
    state = indexing.build_company_index(
        "NVDA",
        as_of,
        DEFAULT_INDEX_CONFIG,
        engine=Mock(),
    )

    assert calls == ["document", "blocks", "chunks", "embeddings", "index"]
    assert captured["vectors"] == [[0.0]]
    assert captured["index"]["document_versions"] == {
        document.document_id: document.content_hash,
    }
    assert captured["index"]["chunk_count"] == state.chunk_count == 1


def test_retrieve_knowledge_returns_historical_data_mode(monkeypatch):
    engine = Mock()
    embeddings = Mock()
    embeddings.embed_query.return_value = [0.1] * 768
    monkeypatch.setattr(
        knowledge,
        "ensure_company_index",
        lambda **kwargs: {
            "document_versions": {"sec:document": "content-hash"},
        },
    )
    monkeypatch.setattr(knowledge, "build_embeddings", lambda *args: embeddings)
    monkeypatch.setattr(
        knowledge,
        "search_similar_chunks",
        lambda **kwargs: [{
            "chunk_id": "document:chunk:0",
            "company_id": "NVDA",
            "document_id": "sec:document",
            "content": "Risk factor content",
        }],
    )

    results = knowledge.retrieve_knowledge(
        "NVDA",
        "What are the risks?",
        datetime(2026, 9, 19, tzinfo=timezone.utc),
        engine=engine,
        config=DEFAULT_INDEX_CONFIG,
    )

    assert results == [{
        "evidence_id": "rag:document:chunk:0",
        "company_id": "NVDA",
        "source": "sec:document",
        "content": "Risk factor content",
        "data_mode": "historical",
    }]


def test_retrieve_knowledge_passes_runtime_dependencies_to_index(monkeypatch):
    engine = Mock()
    calls = []
    search_calls = []
    embedding_configs = []
    embeddings = Mock()
    query_embedding = [0.1] * 768
    embeddings.embed_query.return_value = query_embedding

    def fake_ensure_company_index(**kwargs):
        calls.append(kwargs)
        return {
            "document_versions": {"sec:document": "content-hash"},
        }

    def fake_search_similar_chunks(**kwargs):
        search_calls.append(kwargs)
        return []

    monkeypatch.setattr(knowledge, "ensure_company_index", fake_ensure_company_index)
    monkeypatch.setattr(
        knowledge,
        "build_embeddings",
        lambda model_name, model_revision: (
            embedding_configs.append((model_name, model_revision))
            or embeddings
        ),
    )
    monkeypatch.setattr(knowledge, "search_similar_chunks", fake_search_similar_chunks)

    results = knowledge.retrieve_knowledge(
        "NVDA",
        "What are the risks?",
        datetime(2026, 9, 19, tzinfo=timezone.utc),
        engine=engine,
        config=DEFAULT_INDEX_CONFIG,
    )

    assert results == []
    assert embedding_configs == [(
        DEFAULT_INDEX_CONFIG.embedding_model,
        DEFAULT_INDEX_CONFIG.embedding_revision,
    )]
    assert calls == [{
        "company_id": "NVDA",
        "as_of": datetime(2026, 9, 19, tzinfo=timezone.utc),
        "config": DEFAULT_INDEX_CONFIG,
        "engine": engine,
    }]
    assert search_calls == [{
        "engine": engine,
        "company_id": "NVDA",
        "query_embedding": query_embedding,
        "index_config_id": build_index_config_id(DEFAULT_INDEX_CONFIG),
        "document_versions": {"sec:document": "content-hash"},
        "k": 2,
    }]


def test_implicit_as_of_reuses_existing_stored_index(monkeypatch):
    engine = Mock()
    calls = []
    stored = {
        "company_id": "NVDA",
        "as_of": datetime(2026, 9, 19, tzinfo=timezone.utc),
        "index_config_id": build_index_config_id(DEFAULT_INDEX_CONFIG),
        "document_versions": {"document": "hash"},
        "chunk_count": 1,
    }
    query_results = iter([None, stored, stored])

    def fake_build_company_index(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(indexing, "create_database_engine", lambda: engine)
    monkeypatch.setattr(indexing, "get_company_index", lambda **kwargs: next(query_results))
    monkeypatch.setattr(indexing, "build_company_index", fake_build_company_index)

    first = indexing.ensure_company_index("nvda")
    second = indexing.ensure_company_index("NVDA")

    assert first is second
    assert len(calls) == 1
    assert calls[0]["company_id"] == "NVDA"
    assert calls[0]["as_of"].utcoffset() is not None
    assert calls[0]["config"] == DEFAULT_INDEX_CONFIG
    assert calls[0]["engine"] is engine


def test_as_of_reuse_respects_time_boundary(monkeypatch):
    engine = Mock()
    calls = []
    stored_indexes = []

    def fake_get_company_index(engine, company_id, as_of, index_config_id):
        matches = [
            index
            for index in stored_indexes
            if index["company_id"] == company_id
            and index["as_of"] <= as_of
            and index["index_config_id"] == index_config_id
        ]
        return max(matches, key=lambda index: index["as_of"], default=None)

    def fake_build_company_index(**kwargs):
        calls.append(kwargs)
        stored_indexes.append({
            "company_id": kwargs["company_id"],
            "as_of": kwargs["as_of"],
            "index_config_id": build_index_config_id(kwargs["config"]),
            "document_versions": {"document": "hash"},
            "chunk_count": 1,
        })

    monkeypatch.setattr(indexing, "create_database_engine", lambda: engine)
    monkeypatch.setattr(indexing, "get_company_index", fake_get_company_index)
    monkeypatch.setattr(indexing, "build_company_index", fake_build_company_index)
    first_as_of = datetime(2026, 9, 18, tzinfo=timezone.utc)
    later_as_of = datetime(2026, 9, 19, tzinfo=timezone.utc)
    earlier_as_of = datetime(2026, 9, 17, tzinfo=timezone.utc)

    first = indexing.ensure_company_index("NVDA", first_as_of)
    later = indexing.ensure_company_index("NVDA", later_as_of)
    earlier = indexing.ensure_company_index("NVDA", earlier_as_of)

    assert later is first
    assert earlier is not first
    assert len(calls) == 2


def test_get_company_index_selects_latest_version_before_as_of():
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = None
    as_of = datetime(2026, 9, 19, tzinfo=timezone.utc)

    get_company_index(engine, "NVDA", as_of, "config-id")

    statement = connection.execute.call_args.args[0]
    sql = str(statement)
    params = statement.compile().params
    assert "company_indexes.as_of <=" in sql
    assert "ORDER BY company_indexes.as_of DESC" in sql
    assert params["as_of_1"] == as_of
    assert params["param_1"] == 1


def test_search_similar_chunks_filters_document_versions():
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.all.return_value = []
    document_versions = {
        "document-a": "hash-a",
        "document-b": "hash-b",
    }

    search_similar_chunks(
        engine=engine,
        company_id="NVDA",
        query_embedding=[0.1] * 768,
        index_config_id="config-id",
        document_versions=document_versions,
        k=2,
    )

    statement = connection.execute.call_args.args[0]
    params = statement.compile().params
    assert list(document_versions.items()) in params.values()


def test_save_chunk_embeddings_rejects_wrong_dimension():
    config = DEFAULT_INDEX_CONFIG.model_copy(
        update={"embedding_dimension": 2},
    )

    with pytest.raises(ValueError, match="embedding dimension mismatch"):
        save_chunk_embeddings(
            engine=Mock(),
            chunks=[Mock(chunk_id="chunk-1")],
            embeddings=[[0.1]],
            config=config,
            index_config_id=build_index_config_id(config),
        )
