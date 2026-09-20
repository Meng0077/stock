from datetime import datetime, timezone

from stock_agent.retrieval.index_state import (
    clear_company_index_states,
    get_company_index_state,
)
from stock_agent.retrieval.knowledge import (
    retrieve_knowledge,
)
from stock_agent.retrieval.schemas import (
    DEFAULT_INDEX_CONFIG,
    build_index_config_id,
)



AS_OF = datetime(
    2026,
    9,
    19,
    tzinfo=timezone.utc,
)


def verify_cold_start():
    clear_company_index_states()
    company_id = "AMD"

    config_id = build_index_config_id(
        DEFAULT_INDEX_CONFIG
    )

    before = get_company_index_state(
        company_id,
        AS_OF,
        config_id,
    )

    assert before is None

    results = retrieve_knowledge(
        company_id=company_id,
        question=(
            "What are the company's "
            "main business risks?"
        ),
        as_of=AS_OF,
        k=3,
    )

    after = get_company_index_state(
        company_id,
        AS_OF,
        config_id,
    )

    assert after is not None
    assert after.chunk_count > 0
    assert after.document_versions
    assert results

    for result in results:
        assert (
            result["company_id"]
            == company_id
        )

        assert result["content"]

        assert (
            result["evidence_id"]
            .startswith("rag:")
        )

        assert result["source"]
        assert result["data_mode"] == "historical"

    print(
        "PASS cold start",
        company_id,
        "documents:",
        len(after.document_versions),
        "chunks:",
        after.chunk_count,
    )

def verify_second_query_reuses_index():
    clear_company_index_states()

    company_id = "AMD"

    first_results = retrieve_knowledge(
        company_id=company_id,
        question=(
            "What are the company's "
            "main business risks?"
        ),
        as_of=AS_OF,
        k=3,
    )

    config_id = build_index_config_id(
        DEFAULT_INDEX_CONFIG
    )

    first_state = get_company_index_state(
        company_id,
        AS_OF,
        config_id,
    )

    assert first_state is not None

    second_results = retrieve_knowledge(
        company_id=company_id,
        question=(
            "What did management say "
            "about recent performance?"
        ),
        as_of=AS_OF,
        k=3,
    )

    second_state = get_company_index_state(
        company_id,
        AS_OF,
        config_id,
    )

    assert second_state is first_state

    assert first_results
    assert second_results

    print(
        "PASS second query reused index"
    )

def verify_retrieval_evidence():
    clear_company_index_states()

    results = retrieve_knowledge(
        company_id="AMD",
        question=(
            "What are the major "
            "risk factors?"
        ),
        as_of=AS_OF,
        k=3,
    )

    assert results

    evidence_ids = {
        result["evidence_id"]
        for result in results
    }

    assert (
        len(evidence_ids)
        == len(results)
    )

    for evidence_id in evidence_ids:
        assert evidence_id.startswith(
            "rag:"
        )

        assert ":chunk:" in evidence_id

    print(
        "PASS retrieval evidence",
        evidence_ids,
    )

def verify_as_of_isolation():
    clear_company_index_states()

    company_id = "AMD"

    older_as_of = datetime(
        2026,
        6,
        1,
        tzinfo=timezone.utc,
    )

    newer_as_of = AS_OF

    retrieve_knowledge(
        company_id=company_id,
        question="What are the risks?",
        as_of=older_as_of,
        k=2,
    )

    retrieve_knowledge(
        company_id=company_id,
        question="What are the risks?",
        as_of=newer_as_of,
        k=2,
    )

    config_id = build_index_config_id(
        DEFAULT_INDEX_CONFIG
    )

    old_state = get_company_index_state(
        company_id,
        older_as_of,
        config_id,
    )

    new_state = get_company_index_state(
        company_id,
        newer_as_of,
        config_id,
    )

    assert old_state is not None
    assert new_state is not None

    assert old_state is not new_state

    print(
        "PASS as_of isolation"
    )


def main():
    verify_cold_start()
    verify_second_query_reuses_index()
    verify_retrieval_evidence()
    verify_as_of_isolation()


if __name__ == "__main__":
    main()
