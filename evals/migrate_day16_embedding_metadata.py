import hashlib
import json

from sqlalchemy import text

from stock_agent.retrieval.schemas import (
    DEFAULT_INDEX_CONFIG,
    build_index_config_id,
)
from stock_agent.storage.database import create_database_engine


def build_previous_index_config_id() -> str:
    payload = {
        "chunk_size": DEFAULT_INDEX_CONFIG.chunk_size,
        "chunk_overlap": DEFAULT_INDEX_CONFIG.chunk_overlap,
        "embedding_model": DEFAULT_INDEX_CONFIG.embedding_model,
        "parser_version": DEFAULT_INDEX_CONFIG.parser_version,
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def main() -> None:
    engine = create_database_engine()
    previous_config_id = build_previous_index_config_id()
    current_config_id = build_index_config_id(DEFAULT_INDEX_CONFIG)

    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE chunk_embeddings "
            "ADD COLUMN IF NOT EXISTS embedding_revision VARCHAR"
        ))
        connection.execute(text(
            "ALTER TABLE chunk_embeddings "
            "ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER"
        ))
        connection.execute(
            text(
                "UPDATE chunk_embeddings SET "
                "embedding_revision = COALESCE(embedding_revision, :revision), "
                "embedding_dimension = COALESCE("
                "embedding_dimension, vector_dims(embedding))"
            ),
            {"revision": DEFAULT_INDEX_CONFIG.embedding_revision},
        )
        connection.execute(text(
            "ALTER TABLE chunk_embeddings "
            "ALTER COLUMN embedding_revision SET NOT NULL"
        ))
        connection.execute(text(
            "ALTER TABLE chunk_embeddings "
            "ALTER COLUMN embedding_dimension SET NOT NULL"
        ))
        embedding_count = connection.execute(
            text(
                "UPDATE chunk_embeddings SET index_config_id = :current "
                "WHERE index_config_id = :previous"
            ),
            {
                "previous": previous_config_id,
                "current": current_config_id,
            },
        ).rowcount
        index_count = connection.execute(
            text(
                "UPDATE company_indexes SET index_config_id = :current "
                "WHERE index_config_id = :previous"
            ),
            {
                "previous": previous_config_id,
                "current": current_config_id,
            },
        ).rowcount

    print("embeddings migrated:", embedding_count)
    print("company indexes migrated:", index_count)
    print("index config id:", current_config_id)


if __name__ == "__main__":
    main()
