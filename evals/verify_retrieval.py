from pathlib import Path

from stock_agent.retrieval.loader import load_text_file
from stock_agent.retrieval.splitter import split_documents
from stock_agent.retrieval.vector_store import build_vector_store
from stock_agent.retrieval.retriever import build_retriever


CASES = [
    {
        "name": "nvda_data_center",
        "company_id": "NVDA",
        "question": "What drives NVIDIA's data center business?",
        "expected_text": "AI computing infrastructure",
    },
    {
        "name": "amd_products",
        "company_id": "AMD",
        "question": "What products does AMD develop?",
        "expected_text": "Ryzen",
    },
]

ROOT = Path(__file__).resolve().parents[1]

def build_documents():

    return [
        load_text_file(
            Path("backend/fixtures/data/nvda.txt"),
            "NVDA",
        ),
        load_text_file(
            Path("backend/fixtures/data/amd.txt"),
            "AMD",
        ),
    ]

def verify_case(store, case):
    retriever = build_retriever(
        store,
        company_id=case["company_id"],
        k=2
    )
    results = retriever.invoke(case["question"])

    for result in results:
        assert (result.metadata["company_id"] == case["company_id"])
        assert "evidence_id" in result.metadata


    contents = [" ".join(result.page_content.split()) for result in results]

    matched = any(case["expected_text"] in content for content in contents)

    print("PASS" if matched else "FAIL", case["name"], )

    if not matched:
        for result in results:
            print('________')
            print(result.metadata)
            print(result.page_content)
    return matched

def main():
    documents = build_documents()
    chunks = split_documents(documents)
    store = build_vector_store(chunks)

    results = [
        verify_case(store, case)
        for case in CASES
    ]

    if not all(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
