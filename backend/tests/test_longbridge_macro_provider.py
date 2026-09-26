from datetime import date

import pytest
from longbridge.openapi import OpenApiException

from stock_agent.macro.errors import MacroDataProviderError
from stock_agent.macro.providers.longbridge_macro import (
    LongbridgeMacroProvider,
)


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = 0

    def macroeconomic(self, *args, **kwargs):
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def rate_limit(message: str = "retry after: 0.6s") -> OpenApiException:
    return OpenApiException(None, 429002, "trace", message)


def make_provider(client: FakeClient, *, max_attempts: int = 3):
    now = [0.0]
    sleeps = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    provider = LongbridgeMacroProvider(
        client,
        min_interval_seconds=1.5,
        max_attempts=max_attempts,
        clock=lambda: now[0],
        sleep=sleep,
    )
    return provider, sleeps


def fetch_page(provider: LongbridgeMacroProvider):
    return provider._fetch_page(
        code="30771890",
        start_date=date(2026, 9, 4),
        end_date=date(2026, 9, 4),
        offset=0,
    )


def test_rate_limit_is_retried_and_then_succeeds():
    expected = object()
    client = FakeClient([rate_limit(), expected])
    provider, sleeps = make_provider(client)

    assert fetch_page(provider) is expected
    assert client.calls == 2
    assert sleeps == [1.5]


def test_rate_limit_stops_after_max_attempts():
    client = FakeClient([rate_limit(), rate_limit(), rate_limit()])
    provider, sleeps = make_provider(client)

    with pytest.raises(
        MacroDataProviderError,
        match="rate limit persists",
    ):
        fetch_page(provider)

    assert client.calls == 3
    assert sleeps == [1.5, 1.5]


def test_other_openapi_error_is_not_retried():
    error = OpenApiException(None, 401001, "trace", "unauthorized")
    client = FakeClient([error])
    provider, sleeps = make_provider(client)

    with pytest.raises(
        MacroDataProviderError,
        match="code=401001",
    ):
        fetch_page(provider)

    assert client.calls == 1
    assert sleeps == []


def test_programming_error_is_not_caught_or_retried():
    client = FakeClient([RuntimeError("bug")])
    provider, sleeps = make_provider(client)

    with pytest.raises(RuntimeError, match="bug"):
        fetch_page(provider)

    assert client.calls == 1
    assert sleeps == []
