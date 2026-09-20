from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from stock_agent.documents.schemas import DocumentChunk
from stock_agent.retrieval.schemas import IndexConfig
from stock_agent.storage.tables import (
    chunk_embeddings,
    document_chunks,
)


def save_chunk_embeddings(
    engine: Engine,
    chunks: list[DocumentChunk],
    embeddings: list[list[float]],
    config: IndexConfig,
    index_config_id: str,
) -> int:

    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings length mismatch")

    if not chunks:
        return 0

    if any(
        len(embedding) != config.embedding_dimension
        for embedding in embeddings
    ):
        raise ValueError("embedding dimension mismatch")

    values = [
        {
            "chunk_id": chunk.chunk_id,
            "index_config_id": index_config_id,
            "embedding_model": (
                config.embedding_model
            ),
            "embedding_revision": (
                config.embedding_revision
            ),
            "embedding_dimension": (
                config.embedding_dimension
            ),
            "embedding": embedding,
        }
        for chunk, embedding in zip(
            chunks,
            embeddings,
            strict=True,
        )
    ]

    statement = insert(chunk_embeddings).values(
        values
    ).on_conflict_do_nothing(
        index_elements=[
            chunk_embeddings.c.chunk_id,
            chunk_embeddings.c.index_config_id,
        ]
    ).returning(
        chunk_embeddings.c.chunk_id,
    )

    with engine.begin() as connection:
        result = connection.execute(statement)
        return len(result.all())

def search_similar_chunks(
    engine: Engine,
    company_id: str,
    query_embedding: list[float],
    index_config_id: str,
    document_versions: dict[str, str],
    k: int = 5,
) -> list[dict]:
    distance = (
        chunk_embeddings.c.embedding
        .cosine_distance(query_embedding)
        .label("distance")
    )

    statement = (
        select(
            document_chunks,
            distance,
        )
        .join(
            chunk_embeddings,
            chunk_embeddings.c.chunk_id
            == document_chunks.c.chunk_id,
        )
        .where(
            document_chunks.c.company_id
            == company_id,
            chunk_embeddings.c.index_config_id
            == index_config_id,
            tuple_(
                document_chunks.c.document_id,
                document_chunks.c.document_content_hash,
            ).in_(list(document_versions.items())),
        )
        .order_by(distance)
        .limit(k)
    )

    with engine.connect() as connection:
        rows = (
            connection.execute(statement)
            .mappings()
            .all()
        )

    return [
        dict(row)
        for row in rows
    ]
