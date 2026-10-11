from unittest.mock import Mock

import pytest

from stock_agent.company import registry
from stock_agent.company.registry import (
    SecurityRecord,
    SecurityRegistryUnavailableError,
)
from stock_agent.documents import sec_provider
from stock_agent.market.errors import MarketDataProviderError
from stock_agent.market.schemas import SecurityInfo


def test_build_sec_security_index_uses_official_payload_fields() -> None:
    index = registry.build_sec_security_index(
        {
            "0": {
                "cik_str": 1045810,
                "ticker": "nvda",
                "title": "NVIDIA CORP",
            },
        }
    )

    assert index == {
        "NVDA": SecurityRecord(
            symbol="NVDA",
            name="NVIDIA CORP",
            cik="0001045810",
        ),
    }


def test_lookup_security_uses_sec_without_market_fallback(monkeypatch) -> None:
    security = SecurityRecord(
        symbol="NVDA",
        name="NVIDIA CORP",
        cik="0001045810",
    )
    monkeypatch.setattr(
        registry,
        "find_sec_security",
        Mock(return_value=security),
    )
    fallback_factory = Mock()

    result = registry.lookup_security(
        " nvda ",
        fallback_provider_factory=fallback_factory,
    )

    assert result is security
    fallback_factory.assert_not_called()


def test_lookup_security_uses_market_fallback_for_non_sec_security(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        registry,
        "find_sec_security",
        Mock(return_value=None),
    )
    provider = Mock()
    provider.get_security_info.return_value = SecurityInfo(
        symbol="QQQ",
        name="Invesco QQQ Trust",
    )

    result = registry.lookup_security(
        "qqq",
        fallback_provider_factory=lambda: provider,
    )

    assert result == SecurityRecord(
        symbol="QQQ",
        name="Invesco QQQ Trust",
        cik=None,
    )
    provider.get_security_info.assert_called_once_with("QQQ")


def test_lookup_security_does_not_treat_provider_failure_as_unknown(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        registry,
        "find_sec_security",
        Mock(return_value=None),
    )
    provider = Mock()
    provider.get_security_info.side_effect = MarketDataProviderError(
        "temporary"
    )

    with pytest.raises(SecurityRegistryUnavailableError):
        registry.lookup_security(
            "QQQ",
            fallback_provider_factory=lambda: provider,
        )


def test_existing_ticker_to_cik_reuses_company_registry(monkeypatch) -> None:
    find_security = Mock(
        return_value=SecurityRecord(
            symbol="NVDA",
            name="NVIDIA CORP",
            cik="0001045810",
        )
    )
    monkeypatch.setattr(
        sec_provider,
        "find_sec_security",
        find_security,
    )

    assert sec_provider.ticker_to_cik("nvda") == "0001045810"
    find_security.assert_called_once_with("nvda")
