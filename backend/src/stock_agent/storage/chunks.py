from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from stock_agent.documents.schemas import DocumentChunk
from stock_agent.retrieval.schemas import (
    IndexConfig,
    build_chunk_config_id,
)
from stock_agent.storage.tables import (
    document_chunks,
)


def save_document_chunks(
    engine: Engine,
    chunks: list[DocumentChunk],
    config: IndexConfig,
) -> int:

    if not chunks:
        return 0

    chunk_config_id = build_chunk_config_id(
        config
    )

    values = [
        {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "document_content_hash": (
                chunk.document_content_hash
            ),
            "company_id": chunk.company_id,
            "chunk_config_id": (
                chunk_config_id
            ),
            "chunk_index": chunk.chunk_index,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "content": chunk.content,
            "source_block_ids": (
                chunk.source_block_ids
            ),
        }
        for chunk in chunks
    ]

    statement = insert(document_chunks).values(
        values).on_conflict_do_nothing(
            index_elements=[
                document_chunks.c.chunk_id,
            ]
        ).returning(
            document_chunks.c.chunk_id,
        )

    with engine.begin() as connection:
        result = connection.execute(statement)
        return len(result.all())


def get_document_chunks(
    engine: Engine,
    document_id: str,
    content_hash: str,
    config: IndexConfig,
) -> list[dict]:
    chunk_config_id = build_chunk_config_id(config)
    statement = select(document_chunks).where(
        document_chunks.c.document_id == document_id,
        document_chunks.c.document_content_hash == content_hash,
        document_chunks.c.chunk_config_id == chunk_config_id,
    ).order_by(document_chunks.c.chunk_index)

    with engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()

    return [dict(row) for row in rows]

def get_document_chunk(
    engine: Engine,
    chunk_id: str,
) -> dict | None:
    statement = (
        select(document_chunks)
        .where(
            document_chunks.c.chunk_id
            == chunk_id
        )
    )

    with engine.connect() as connection:
        row = (
            connection.execute(statement)
            .mappings()
            .one_or_none()
        )

    if row is None:
        return None

    return dict(row)
