import httpx
import pytest

from stock_agent.documents import sec_http


@pytest.fixture(autouse=True)
def reset_rate_limit():
    sec_http._NEXT_REQUEST_AT = 0.0
    yield
    sec_http._NEXT_REQUEST_AT = 0.0


def make_response(
    status_code: int,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers=headers,
        request=httpx.Request("GET", "https://www.sec.gov/example"),
    )


def test_retries_sec_503_then_returns_success(monkeypatch):
    responses = [
        make_response(503, {"Retry-After": "0"}),
        make_response(200),
    ]
    calls = []

    def get(url):
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(sec_http.SEC_CLIENT, "get", get)
    monkeypatch.setattr(sec_http, "wait_for_rate_limit", lambda: None)
    monkeypatch.setattr(sec_http.time, "sleep", lambda _: None)

    response = sec_http.get_sec("https://www.sec.gov/example")

    assert response.status_code == 200
    assert len(calls) == 2


def test_exhausted_sec_503_has_specific_error(monkeypatch):
    calls = []

    def get(url):
        calls.append(url)
        return make_response(503, {"Retry-After": "0"})

    monkeypatch.setattr(sec_http.SEC_CLIENT, "get", get)
    monkeypatch.setattr(sec_http, "wait_for_rate_limit", lambda: None)
    monkeypatch.setattr(sec_http.time, "sleep", lambda _: None)

    with pytest.raises(sec_http.SecServiceUnavailableError):
        sec_http.get_sec("https://www.sec.gov/example")

    assert len(calls) == sec_http.SEC_MAX_RETRIES + 1


def test_exhausted_proxy_error_has_specific_error(monkeypatch):
    calls = []

    def get(url):
        calls.append(url)
        raise httpx.ProxyError(
            "proxy unavailable",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(sec_http.SEC_CLIENT, "get", get)
    monkeypatch.setattr(sec_http, "wait_for_rate_limit", lambda: None)
    monkeypatch.setattr(sec_http.time, "sleep", lambda _: None)

    with pytest.raises(sec_http.SecProxyUnavailableError):
        sec_http.get_sec("https://www.sec.gov/example")

    assert len(calls) == sec_http.SEC_MAX_RETRIES + 1


def test_non_retryable_http_error_is_not_retried(monkeypatch):
    calls = []

    def get(url):
        calls.append(url)
        return make_response(404)

    monkeypatch.setattr(sec_http.SEC_CLIENT, "get", get)
    monkeypatch.setattr(sec_http, "wait_for_rate_limit", lambda: None)

    with pytest.raises(httpx.HTTPStatusError):
        sec_http.get_sec("https://www.sec.gov/example")

    assert len(calls) == 1


def test_rate_limit_spaces_request_starts(monkeypatch):
    sleeps = []

    monkeypatch.setattr(sec_http.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(sec_http.time, "sleep", sleeps.append)

    sec_http.wait_for_rate_limit()
    sec_http.wait_for_rate_limit()

    assert sleeps == [pytest.approx(1 / sec_http.SEC_REQUESTS_PER_SECOND)]
