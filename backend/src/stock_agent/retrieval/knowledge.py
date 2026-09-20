from datetime import datetime, timezone

from sqlalchemy import Engine

from stock_agent.storage.database import create_database_engine
from stock_agent.storage.embeddings import search_similar_chunks
from stock_agent.retrieval.indexing import ensure_company_index
from stock_agent.retrieval.schemas import (
    DEFAULT_INDEX_CONFIG,
    IndexConfig,
    build_index_config_id,
)
from stock_agent.retrieval.chunking import build_evidence_id
from stock_agent.retrieval.embeddings import build_embeddings


def retrieve_knowledge(
    company_id: str,
    question: str,
    as_of: datetime | None = None,
    k: int = 2,
    *,
    engine: Engine | None = None,
    config: IndexConfig = DEFAULT_INDEX_CONFIG,
) -> list[dict]:
    if engine is None:
        engine = create_database_engine()
    if as_of is None:
        as_of = datetime.now(timezone.utc)

    index = ensure_company_index(
        company_id=company_id,
        as_of=as_of,
        config=config,
        engine=engine,
    )
    index_config_id = build_index_config_id(config)
    embeddings = build_embeddings(
        config.embedding_model,
        config.embedding_revision,
    )
    query_embedding = embeddings.embed_query(question)
    if len(query_embedding) != config.embedding_dimension:
        raise ValueError("query embedding dimension mismatch")

    rows = search_similar_chunks(
        engine=engine,
        company_id=company_id,
        query_embedding=query_embedding,
        index_config_id=index_config_id,
        document_versions=index["document_versions"],
        k=k,
    )

    return [
        {
            "evidence_id": build_evidence_id(row["chunk_id"]),
            "company_id": row["company_id"],
            "source": row["document_id"],
            "content": row["content"],
            "data_mode": "historical",
        }
        for row in rows
    ]


if __name__ == "__main__":
    results = retrieve_knowledge(
        company_id="NVDA",
        question="What drove revenue growth?",
        as_of=datetime(
            2026,
            9,
            19,
            tzinfo=timezone.utc,
        ),
        k=3,
    )

    for result in results:
        print()
        print("evidence:", result["evidence_id"])
        print("source:", result["source"])
        print(result["content"][:500])
