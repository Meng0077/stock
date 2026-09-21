from datetime import datetime, timezone

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore

from stock_agent.documents.schemas import DocumentChunk, FilingMetadata
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
from sqlalchemy.engine import Engine
from stock_agent.storage.blocks import save_filing_blocks
from stock_agent.storage.chunks import save_document_chunks
from stock_agent.storage.database import (
    create_database_engine,
    create_database_tables,
)
from stock_agent.storage.documents import (
    get_indexed_accession_numbers,
    save_filing_document,
)
from stock_agent.storage.embeddings import save_chunk_embeddings
from stock_agent.storage.indexes import (
    get_company_index,
    get_latest_compatible_company_index,
    save_company_index,
)


KNOWLEDGE_FORMS = SUPPORTED_FORMS | {"8-K"}


def to_langchain_document(chunk: DocumentChunk) -> Document:
    return Document(
        id=chunk.chunk_id,
        page_content=chunk.content,
        metadata={
            "chunk_id": chunk.chunk_id,
            "evidence_id": build_evidence_id(chunk.chunk_id),
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
        embedding_revision=config.embedding_revision,
    )


def build_company_index(
    company_id: str,
    as_of: datetime,
    config: IndexConfig,
    engine: Engine | None = None,
) -> CompanyIndexState:
    if engine is None:
        engine = create_database_engine()
    create_database_tables(engine)

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
        save_filing_document(engine, document)

        save_filing_blocks(engine, document)

        chunks.extend(split_filing_document(document, config))

    if not chunks:
        raise ValueError(f"no chunks created for {company_id}")
    save_document_chunks(engine, chunks, config)


    vector_store = build_company_vector_store(chunks, config)
    vectors = [
        vector_store.store[chunk.chunk_id]["vector"]
        for chunk in chunks
    ]

    index_config_id = build_index_config_id(config)
    save_chunk_embeddings(
        engine,
        chunks,
        vectors,
        config,
        index_config_id,
    )
    document_versions = {
        document.document_id: document.content_hash
        for document in documents
    }
    save_company_index(
        engine=engine,
        company_id=company_id,
        as_of=as_of,
        index_config_id=index_config_id,
        document_versions=document_versions,
        chunk_count=len(chunks),
    )
    state = CompanyIndexState(
        company_id=company_id,
        as_of=as_of,
        config=config,
        config_id=index_config_id,
        document_versions=document_versions,
        vector_store=vector_store,
        chunk_count=len(chunks),
    )
    save_company_index_state(state)
    return state


def ensure_company_index(
    company_id: str,
    as_of: datetime | None = None,
    config: IndexConfig = DEFAULT_INDEX_CONFIG,
    engine: Engine | None = None,
) -> dict:
    company_id = company_id.upper()
    if engine is None:
        engine = create_database_engine()
    if as_of is None:
        as_of = datetime.now(timezone.utc)

    index_config_id = build_index_config_id(config)

    exact_index = get_company_index(
        engine=engine,
        company_id=company_id,
        as_of=as_of,
        index_config_id=index_config_id,
    )
    if exact_index is not None:
        return exact_index

    base_index = get_latest_compatible_company_index(
        engine=engine,
        company_id=company_id,
        as_of=as_of,
        index_config_id=index_config_id,
    )

    if base_index is None:
        build_company_index(
            engine=engine,
            company_id=company_id,
            as_of=as_of,
            config=config,
        )
    else:
        indexed_accessions = get_indexed_accession_numbers(
            engine,
            document_versions=base_index["document_versions"],
        )
        available_filings = get_recent_filings(
            company_id,
            as_of,
            forms=KNOWLEDGE_FORMS,
            limit=10,
        )
        new_filings = find_new_filings(
            available_filings,
            indexed_accessions,
        )

        new_document_versions = {}
        new_chunks = []
        if new_filings:
            new_document_versions, new_chunks = process_new_filings(
                engine,
                new_filings,
                config,
            )
            embed_new_chunks(engine, new_chunks, config)

        save_company_index(
            engine=engine,
            company_id=company_id,
            as_of=as_of,
            index_config_id=index_config_id,
            document_versions={
                **base_index["document_versions"],
                **new_document_versions,
            },
            chunk_count=(
                base_index["chunk_count"]
                + len(new_chunks)
            ),
        )

    stored = get_company_index(
        engine=engine,
        company_id=company_id,
        as_of=as_of,
        index_config_id=index_config_id,
    )

    if stored is None:
        raise RuntimeError(
            "company index was not persisted"
        )

    return stored


# 找出此次要新增的filings
def find_new_filings(
    available_filings: list[FilingMetadata],
    indexed_accessions: set[str],
) -> list[FilingMetadata]:
    return [
        filing for filing in available_filings
        if filing.accession_number not in indexed_accessions
    ]


# 处理此次新增
def process_new_filings(
    engine: Engine,
    new_filings: list[FilingMetadata],
    config: IndexConfig,
) -> tuple[dict[str, str], list[DocumentChunk]]:
    new_document_versions: dict[str, str] = {}
    new_chunks: list[DocumentChunk] = []

    for filing in new_filings:
        documents = load_relevant_filing_documents(filing)
        for document in documents:
            save_filing_document(engine, document)
            save_filing_blocks(engine, document)

            chunks = split_filing_document(document, config)
            save_document_chunks(engine, chunks, config)

            new_document_versions[document.document_id] = document.content_hash
            new_chunks.extend(chunks)

    return (
        new_document_versions,
        new_chunks,
    )


# 处理新增的embeddings
def embed_new_chunks(
    engine: Engine,
    chunks: list[DocumentChunk],
    config: IndexConfig,
) -> int:
    if not chunks:
        return 0

    index_config_id = build_index_config_id(config)

    vector_store = build_company_vector_store(chunks, config)
    embedding_vectors = [
        vector_store.store[chunk.chunk_id]["vector"]
        for chunk in chunks
    ]

    return save_chunk_embeddings(
        engine=engine,
        chunks=chunks,
        embeddings=embedding_vectors,
        config=config,
        index_config_id=index_config_id,
    )
