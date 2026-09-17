from langchain_core.vectorstores import InMemoryVectorStore

from stock_agent.retrieval.embeddings import build_embeddings


def build_vector_store(documents):
    embeddings = build_embeddings()
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
