# from langchain_core.embeddings import FakeEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings

from stock_agent.retrieval.schemas import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_REVISION,
)


def build_embeddings(
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    model_revision: str = DEFAULT_EMBEDDING_REVISION,
):
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={
            "device": "cpu",
            "revision": model_revision,
        },
        encode_kwargs={
            "normalize_embeddings": True,
        },
    )


if __name__ == "__main__":

    texts = [
        "NVIDIA has a large data center business.",
        "AMD develops CPUs and GPUs.",
    ]

    embeddings = build_embeddings()
    vector = embeddings.embed_query(
        "NVDA data center business"
    )
    print("dimension:", len(vector))
    print(vector[:5])

    # vectors = embeddings.embed_documents(texts=texts)
    # print(len(vectors))
    # print(len(vectors[0]))
