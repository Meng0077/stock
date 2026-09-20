from datetime import datetime, timezone

from stock_agent.retrieval.indexing import ensure_company_index


def retrieve_knowledge(
    company_id: str,
    question: str,
    as_of: datetime | None = None,
    k: int = 2,
) -> list[dict]:
    state = ensure_company_index(company_id, as_of)
    documents = state.vector_store.similarity_search(query=question, k=k)

    return [
        {
            "evidence_id": document.metadata["evidence_id"],
            "company_id": document.metadata["company_id"],
            "source": document.metadata["source_url"],
            "content": document.page_content,
            "data_mode": "historical",
        }
        for document in documents
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
