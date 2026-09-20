import argparse
from datetime import datetime, timezone

import stock_agent.retrieval.indexing as indexing

from stock_agent.retrieval.knowledge import (
    retrieve_knowledge,
)
from stock_agent.retrieval.schemas import (
    DEFAULT_INDEX_CONFIG,
)
from stock_agent.storage.database import (
    create_database_engine,
)
from stock_agent.storage.evidence import (
    resolve_rag_evidence,
)

COMPANY_ID = "NVDA"

AS_OF = datetime(
    2026,
    9,
    20,
    tzinfo=timezone.utc,
)

QUESTION = (
    "What does the latest SEC filing say "
    "about revenue?"
)

def run_build() -> None:
    engine = create_database_engine()

    results = retrieve_knowledge(
        company_id=COMPANY_ID,
        engine=engine,
        as_of=AS_OF,
        question=QUESTION,
        config=DEFAULT_INDEX_CONFIG,
        k=3,
    )

    assert results

    print('results', results)

    assert all(
        item["evidence_id"].startswith("rag:")
        for item in results
    )

    print(
        "build/retrieve passed:",
        len(results),
    )

def run_reuse() -> None:
    engine = create_database_engine()

    def fail_if_build_called(*args, **kwargs):
        raise AssertionError(
            "build_company_index should not "
            "be called during persistent reuse"
        )

    indexing.build_company_index = (
        fail_if_build_called
    )

    results = retrieve_knowledge(
        engine=engine,
        company_id=COMPANY_ID,
        question=QUESTION,
        as_of=AS_OF,
        config=DEFAULT_INDEX_CONFIG,
        k=3,
    )

    assert results

    resolved = resolve_rag_evidence(
        engine,
        results[0]["evidence_id"],
    )

    assert resolved is not None

    assert (
        resolved["chunk"]["content"]
        == results[0]["content"]
    )

    assert (
        resolved["document"]["source_url"]
    )

    print(
        "persistent reuse passed:",
        len(results),
    )

    print(
        "source:",
        resolved["document"]["source_url"],
    )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=[
            "build",
            "reuse",
        ],
        required=True,
    )

    args = parser.parse_args()

    if args.mode == "build":
        run_build()
    else:
        run_reuse()


if __name__ == "__main__":
    main()
