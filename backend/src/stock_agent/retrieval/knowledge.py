from pathlib import Path

from stock_agent.retrieval.loader import load_text_file
from stock_agent.retrieval.splitter import split_documents
from stock_agent.retrieval.vector_store import build_vector_store
from stock_agent.retrieval.retriever import build_retriever


ROOT = Path(__file__).resolve().parents[4]
KNOWLEDGE_DIR = (
    ROOT
    / "backend"
    / "fixtures"
    / "data"
)

def get_knowledge_path(
    company_id: str,
) -> Path:
    return KNOWLEDGE_DIR / f"{company_id.lower()}.txt"


def retrieve_knowledge(
    company_id: str,
    question: str,
    k: int = 2,
):
    path = get_knowledge_path(company_id)
    if not path.exists():
        return []

    documents = load_text_file(path, company_id=company_id)

    chunks = split_documents([documents])

    store = build_vector_store(chunks)

    retrieve = build_retriever(store, company_id=company_id, k=k)

    results = retrieve.invoke(question)

    return [
        {
            "evidence_id": result.metadata[
                "evidence_id"
            ],
            "company_id": result.metadata[
                "company_id"
            ],
            "source": result.metadata[
                "source"
            ],
            "content": result.page_content,
        }
        for result in results
    ]


if __name__ == "__main__":
    results = retrieve_knowledge(
        company_id="NVDA",
        question=(
            "What drives NVIDIA's "
            "data center business?"
        ),
    )

    for result in results:
        print("-----")
        print(result)
