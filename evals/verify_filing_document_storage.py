from sqlalchemy import func, select

from stock_agent.documents.sec_loader import (
    load_relevant_filing_documents,
)
from stock_agent.documents.sec_provider import (
    get_recent_filings,
)
from stock_agent.retrieval.chunking import (
    split_filing_document,
)
from stock_agent.retrieval.embeddings import (
    build_embeddings,
)
from stock_agent.retrieval.schemas import (
    DEFAULT_INDEX_CONFIG,
    build_index_config_id,
)
from stock_agent.storage.database import (
    create_database_engine,
    create_database_tables,
)
from stock_agent.storage.blocks import (
    get_filing_blocks,
    save_filing_blocks,
)
from stock_agent.storage.documents import (
    get_filing_document,
    save_filing_document,
)
from stock_agent.storage.embeddings import (
    save_chunk_embeddings,
)
from stock_agent.storage.chunks import (
    get_document_chunks,
    save_document_chunks,
)
from stock_agent.storage.tables import (
    filing_documents,
)


def load_document():
    filing = get_recent_filings(
        company_id="NVDA",
        forms={"10-Q"},
        limit=1,
    )[0]
    return load_relevant_filing_documents(filing)[0]


def main():
    document = load_document()
    engine = create_database_engine()
    create_database_tables(engine)

    first_saved = save_filing_document(
        engine,
        document,
    )
    second_saved = save_filing_document(
        engine,
        document,
    )
    stored = get_filing_document(
        engine,
        document.document_id,
        document.content_hash,
    )

    statement = (
        select(func.count())
        .select_from(filing_documents)
    )
    with engine.connect() as connection:
        count = connection.scalar(statement)

    print("first:", first_saved)
    print("second:", second_saved)
    print("stored:", stored is not None)
    print("count:", count)

    inserted = save_filing_blocks(
        engine,
        document,
    )
    stored_blocks = get_filing_blocks(
        engine,
        document.document_id,
        document.content_hash,
    )
    inserted_again = save_filing_blocks(
        engine,
        document,
    )

    print("blocks inserted:", inserted)
    print("blocks stored:", len(stored_blocks))
    print("blocks original:", len(document.blocks))
    print("blocks inserted again:", inserted_again)

    for block in stored_blocks:
        actual = document.content[
            block["start_char"]:
            block["end_char"]
        ]
        assert actual == block["text"]

    chunks = split_filing_document(
        document,
        DEFAULT_INDEX_CONFIG,
    )
    chunks_inserted = save_document_chunks(
        engine,
        chunks,
        DEFAULT_INDEX_CONFIG,
    )
    stored_chunks = get_document_chunks(
        engine,
        document.document_id,
        document.content_hash,
        DEFAULT_INDEX_CONFIG,
    )
    chunks_inserted_again = save_document_chunks(
        engine,
        chunks,
        DEFAULT_INDEX_CONFIG,
    )

    print("chunks generated:", len(chunks))
    print("chunks inserted:", chunks_inserted)
    print("chunks stored:", len(stored_chunks))
    print("chunks inserted again:", chunks_inserted_again)

    for chunk in stored_chunks:
        actual = document.content[
            chunk["start_char"]:
            chunk["end_char"]
        ]
        assert actual == chunk["content"]

    valid_block_ids = {
        block.block_id
        for block in document.blocks
    }
    for chunk in stored_chunks:
        assert set(
            chunk["source_block_ids"]
        ).issubset(valid_block_ids)

    embedding_model = build_embeddings(
        DEFAULT_INDEX_CONFIG.embedding_model,
        DEFAULT_INDEX_CONFIG.embedding_revision,
    )
    vectors = embedding_model.embed_documents(
        [chunk.content for chunk in chunks]
    )
    index_config_id = build_index_config_id(
        DEFAULT_INDEX_CONFIG
    )
    embeddings_inserted = save_chunk_embeddings(
        engine,
        chunks,
        vectors,
        DEFAULT_INDEX_CONFIG,
        index_config_id,
    )
    embeddings_inserted_again = save_chunk_embeddings(
        engine,
        chunks,
        vectors,
        DEFAULT_INDEX_CONFIG,
        index_config_id,
    )

    print("vectors generated:", len(vectors))
    print("embeddings inserted:", embeddings_inserted)
    print(
        "embeddings inserted again:",
        embeddings_inserted_again,
    )


if __name__ == "__main__":
    main()
