from langchain_core.vectorstores import InMemoryVectorStore
from langchain_core.documents import Document

from stock_agent.retrieval.embeddings import build_embeddings
from stock_agent.retrieval.schemas import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_REVISION,
)


def build_vector_store(
    documents: list[Document],
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    embedding_revision: str = DEFAULT_EMBEDDING_REVISION,
) -> InMemoryVectorStore:
    embeddings = build_embeddings(
        embedding_model,
        embedding_revision,
    )
    store = InMemoryVectorStore(
        embedding=embeddings
    )
    store.add_documents(documents=documents)
    return store

if __name__ == "__main__":
    from pathlib import Path

    from stock_agent.retrieval.loader import load_text_file
    from stock_agent.retrieval.splitter import split_documents

    documents = [
        load_text_file(
            Path("backend/fixtures/data/nvda.txt"),
            "NVDA",
        ),
        load_text_file(
            Path("backend/fixtures/data/amd.txt"),
            "AMD",
        ),
    ]

    chunks = split_documents(documents)
    store = build_vector_store(chunks)
    results = store.similarity_search("data center GPU", k=2,)
    for result in results:
        print("-----")
        print(result.metadata)
        print(result.page_content)
