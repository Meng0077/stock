from datetime import datetime, timezone

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore

from stock_agent.documents.schemas import DocumentChunk
from stock_agent.documents.sec_loader import load_relevant_filing_documents
from stock_agent.documents.sec_provider import SUPPORTED_FORMS, get_recent_filings
from stock_agent.retrieval.chunking import build_evidence_id, split_filing_document
from stock_agent.retrieval.index_state import (
    CompanyIndexState,
    get_latest_company_index_state,
    save_company_index_state,
)
from stock_agent.retrieval.schemas import (
    DEFAULT_INDEX_CONFIG,
    IndexConfig,
    build_index_config_id,
)
from stock_agent.retrieval.vector_store import build_vector_store


KNOWLEDGE_FORMS = SUPPORTED_FORMS | {"8-K"}


def to_langchain_document(chunk: DocumentChunk) -> Document:
    return Document(
        page_content=chunk.content,
        metadata={
            "chunk_id": chunk.chunk_id,
            "evidence_id": build_evidence_id(chunk),
            "document_id": chunk.document_id,
            "document_content_hash": chunk.document_content_hash,
            "company_id": chunk.company_id,
            "chunk_index": chunk.chunk_index,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "source_url": chunk.source_url,
            "source_block_ids": chunk.source_block_ids,
            "source_xpaths": chunk.source_xpaths,
        },
    )


def to_langchain_documents(chunks: list[DocumentChunk]) -> list[Document]:
    return [to_langchain_document(chunk) for chunk in chunks]


def build_company_vector_store(
    chunks: list[DocumentChunk],
    config: IndexConfig,
) -> InMemoryVectorStore:
    return build_vector_store(
        to_langchain_documents(chunks),
        embedding_model=config.embedding_model,
    )


def build_company_index(
    company_id: str,
    as_of: datetime,
    config: IndexConfig,
) -> CompanyIndexState:
    filings = get_recent_filings(
        company_id,
        as_of,
        forms=KNOWLEDGE_FORMS,
        limit=10,
    )
    if not filings:
        raise ValueError(f"no supported filings found for {company_id}")

    documents = []
    for filing in filings:
        documents.extend(load_relevant_filing_documents(filing))

    if not documents:
        raise ValueError(f"no documents loaded for {company_id}")

    chunks = []
    for document in documents:
        chunks.extend(split_filing_document(document, config))

    if not chunks:
        raise ValueError(f"no chunks created for {company_id}")

    state = CompanyIndexState(
        company_id=company_id,
        as_of=as_of,
        config=config,
        config_id=build_index_config_id(config),
        document_versions={
            document.document_id: document.content_hash
            for document in documents
        },
        vector_store=build_company_vector_store(chunks, config),
        chunk_count=len(chunks),
    )
    save_company_index_state(state)
    return state


def ensure_company_index(
    company_id: str,
    as_of: datetime | None = None,
    config: IndexConfig = DEFAULT_INDEX_CONFIG,
) -> CompanyIndexState:
    company_id = company_id.upper()
    config_id = build_index_config_id(config)
    existing = get_latest_company_index_state(company_id, config_id, as_of)

    if existing is not None:
        return existing

    if as_of is None:
        as_of = datetime.now(timezone.utc)

    return build_company_index(company_id, as_of, config)
