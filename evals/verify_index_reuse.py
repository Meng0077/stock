from datetime import (
    datetime,
    timezone,
)
from unittest.mock import patch

from stock_agent.retrieval.index_state import (
    CompanyIndexState,
    clear_company_index_states,
    save_company_index_state,

)
from stock_agent.retrieval.indexing import (
    ensure_company_index,
)
from stock_agent.retrieval.schemas import (
    DEFAULT_INDEX_CONFIG,
    IndexConfig,
    build_index_config_id,
)

from unittest.mock import Mock

def make_fake_state(
    company_id: str,
    as_of: datetime,
    config: IndexConfig,
) -> CompanyIndexState:
    return CompanyIndexState(
        company_id=company_id,
        as_of=as_of,

        config=config,
        config_id=build_index_config_id(
            config
        ),

        document_versions={
            "document-1":
                "content-hash-1",
        },

        vector_store=Mock(),

        chunk_count=42,
    )

def fake_build_company_index(
    company_id: str,
    as_of: datetime,
    config: IndexConfig,
) -> CompanyIndexState:
    fake_state = make_fake_state(
            company_id=company_id,
            as_of=as_of,
            config=config,
        )
    save_company_index_state(fake_state)
    return fake_state

def verify_same_index_is_reused():
    clear_company_index_states()

    as_of = datetime(
        2026,
        9,
        19,
        tzinfo=timezone.utc,
    )

    with patch(
        "stock_agent.retrieval."
        "indexing.build_company_index",
        side_effect=fake_build_company_index
    ) as build_mock:
        first = ensure_company_index(
            company_id="NVDA",
            as_of=as_of,
        )

        second = ensure_company_index(
            company_id="NVDA",
            as_of=as_of,
        )

        assert first is second

        assert (
            build_mock.call_count
            == 1
        )

        print(
            "PASS same index reused"
        )


def verify_config_change_rebuilds():
    clear_company_index_states()

    as_of = datetime(
        2026,
        9,
        19,
        tzinfo=timezone.utc,
    )

    another_config = IndexConfig(
        chunk_size=1200,
        chunk_overlap=100,
        embedding_model=(
            DEFAULT_INDEX_CONFIG
            .embedding_model
        ),
    )

    with patch(
        "stock_agent.retrieval."
        "indexing.build_company_index",
        side_effect=(
            fake_build_company_index
        ),
    ) as build_mock:
        first = ensure_company_index(
            company_id="NVDA",
            as_of=as_of,
            config=DEFAULT_INDEX_CONFIG,
        )

        second = ensure_company_index(
            company_id="NVDA",
            as_of=as_of,
            config=another_config,
        )

    assert first is not second

    assert (
        build_mock.call_count
        == 2
    )

    print(
        "PASS config change rebuilds"
    )

def verify_later_as_of_reuses_index():
    clear_company_index_states()

    first_as_of = datetime(
        2026,
        9,
        18,
        tzinfo=timezone.utc,
    )

    second_as_of = datetime(
        2026,
        9,
        19,
        tzinfo=timezone.utc,
    )

    with patch(
        "stock_agent.retrieval."
        "indexing.build_company_index",
        side_effect=(
            fake_build_company_index
        ),
    ) as build_mock:
        first = ensure_company_index(
            company_id="NVDA",
            as_of=first_as_of,
        )

        second = ensure_company_index(
            company_id="NVDA",
            as_of=second_as_of,
        )

    assert first is second

    assert (
        build_mock.call_count
        == 1
    )

    print(
        "PASS later as_of reuses index"
    )


def verify_earlier_as_of_rebuilds():
    clear_company_index_states()

    future_as_of = datetime(
        2026,
        9,
        19,
        tzinfo=timezone.utc,
    )

    historical_as_of = datetime(
        2026,
        9,
        18,
        tzinfo=timezone.utc,
    )

    with patch(
        "stock_agent.retrieval."
        "indexing.build_company_index",
        side_effect=(
            fake_build_company_index
        ),
    ) as build_mock:
        future = ensure_company_index(
            company_id="NVDA",
            as_of=future_as_of,
        )

        historical = ensure_company_index(
            company_id="NVDA",
            as_of=historical_as_of,
        )

    assert future is not historical

    assert (
        build_mock.call_count
        == 2
    )

    print(
        "PASS earlier as_of rebuilds"
    )

def main():
    verify_same_index_is_reused()
    verify_config_change_rebuilds()
    verify_later_as_of_reuses_index()
    verify_earlier_as_of_rebuilds()


if __name__ == "__main__":
    main()
