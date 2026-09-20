# from langchain_core.embeddings import FakeEmbeddings
from langchain_huggingface import HuggingFaceEmbeddings

def build_embeddings(
    model_name: str = "sentence-transformers/all-mpnet-base-v2",
):
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={
            "device": "cpu",
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
