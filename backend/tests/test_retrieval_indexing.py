from datetime import date, datetime, timezone
from unittest.mock import Mock

from stock_agent.documents.schemas import (
    SEC_HTML_PARSER_VERSION,
    FilingBlock,
    FilingDocument,
)
from stock_agent.retrieval import indexing
from stock_agent.retrieval.chunking import split_filing_document
from stock_agent.retrieval.knowledge import retrieve_knowledge
from stock_agent.retrieval.index_state import (
    CompanyIndexState,
    clear_company_index_states,
    save_company_index_state,
)
from stock_agent.retrieval.schemas import (
    DEFAULT_INDEX_CONFIG,
    IndexConfig,
    build_index_config_id,
)


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


def test_parser_version_changes_index_identity():
    changed = DEFAULT_INDEX_CONFIG.model_copy(
        update={"parser_version": "sec-html-v2"},
    )

    assert DEFAULT_INDEX_CONFIG.parser_version == SEC_HTML_PARSER_VERSION
    assert build_index_config_id(changed) != build_index_config_id(DEFAULT_INDEX_CONFIG)


def test_retrieve_knowledge_returns_historical_data_mode(monkeypatch):
    document = Mock(
        page_content="Risk factor content",
        metadata={
            "evidence_id": "rag:document:chunk:0",
            "company_id": "NVDA",
            "source_url": "https://example.com/report.htm",
        },
    )
    vector_store = Mock()
    vector_store.similarity_search.return_value = [document]
    state = Mock(vector_store=vector_store)
    monkeypatch.setattr(
        "stock_agent.retrieval.knowledge.ensure_company_index",
        lambda company_id, as_of: state,
    )

    results = retrieve_knowledge("NVDA", "What are the risks?")

    assert results == [{
        "evidence_id": "rag:document:chunk:0",
        "company_id": "NVDA",
        "source": "https://example.com/report.htm",
        "content": "Risk factor content",
        "data_mode": "historical",
    }]


def test_implicit_as_of_reuses_existing_process_index(monkeypatch):
    clear_company_index_states()
    calls = []

    def fake_build_company_index(company_id, as_of, config):
        calls.append((company_id, as_of, config))
        state = CompanyIndexState(
            company_id=company_id,
            as_of=as_of,
            config=config,
            config_id=build_index_config_id(config),
            document_versions={"document": "hash"},
            vector_store=Mock(),
            chunk_count=1,
        )
        save_company_index_state(state)
        return state

    monkeypatch.setattr(indexing, "build_company_index", fake_build_company_index)

    first = indexing.ensure_company_index("nvda")
    second = indexing.ensure_company_index("NVDA")

    assert first is second
    assert len(calls) == 1
    assert calls[0][0] == "NVDA"
    assert calls[0][1].utcoffset() is not None
    assert calls[0][2] == DEFAULT_INDEX_CONFIG


def test_as_of_reuse_respects_time_boundary(monkeypatch):
    clear_company_index_states()
    calls = []

    def fake_build_company_index(company_id, as_of, config):
        calls.append((company_id, as_of, config))
        state = CompanyIndexState(
            company_id=company_id,
            as_of=as_of,
            config=config,
            config_id=build_index_config_id(config),
            document_versions={"document": "hash"},
            vector_store=Mock(),
            chunk_count=1,
        )
        save_company_index_state(state)
        return state

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
