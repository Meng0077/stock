
def build_retriever(store, company_id: str | None, k: int = 2, ):
    return store.as_retriever(
        search_kwargs={
            "k": k,
            "filter": lambda document: ( document.metadata["company_id"] == company_id )
        }
    )


def retrieve_documents(
    retriever,
    question: str,
):
    documents = retriever.invoke(question)

    return [
        {
            "evidence_id": document.metadata[
                "evidence_id"
            ],
            "company_id": document.metadata[
                "company_id"
            ],
            "source": document.metadata["source"],
            "content": document.page_content,
        }
        for document in documents
    ]

if __name__ == "__main__":
    from pathlib import Path

    from stock_agent.retrieval.loader import load_text_file
    from stock_agent.retrieval.splitter import split_documents
    from stock_agent.retrieval.vector_store import build_vector_store

    documents = [
        load_text_file(
            Path("backend/fixtures/data/nvda.txt"),
            "NVDA",
        ),
        load_text_file(
            Path("backend/fixtures/data/amd.txt"),
            "AMD",
        ),
        load_text_file(
            Path("backend/fixtures/data/fomc_2026_09_16.txt"),
            None,
        ),
        load_text_file(
            Path("backend/fixtures/data/monetary_policy_and_stocks.txt"),
            None,
        ),
    ]

    chunks = split_documents(documents=documents)
    store = build_vector_store(chunks)
    # None 仅匹配宏观资料，不代表取消公司过滤。
    cases = [
        ("NVDA", "What drives NVIDIA's data center business?"),
        ("AMD", "What products does AMD develop?"),
        (None, "本次加息还是降息？幅度和新利率区间是多少？"),
        (None, "美联储为什么采取这次行动？"),
        (None, "本次议息可能通过哪些渠道影响股市？"),
        (None, "加息是否意味着纳斯达克当天一定下跌？"),
        (None, "议息后标普 500 和 NVDA 实际跌了多少？"),
    ]

    for company_id, question in cases:
        retriever = build_retriever(store=store, company_id=company_id, k=2)
        print("\nQUESTION:", question)

        results = retrieve_documents(retriever, question)

        for document in results:
            print("-----")
            print("evidence_id:", document["evidence_id"])
            print("company_id:", document["company_id"])
            print("source:", document["source"])
            print(document["content"])
