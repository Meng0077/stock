import random
import threading
import time
from typing import Any

import httpx


SEC_HEADERS = {
    "User-Agent": "demo-agent 314885503@qq.com",
}

SEC_REQUESTS_PER_SECOND = 3
SEC_MAX_RETRIES = 3
SEC_RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}
SEC_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)

SEC_CLIENT = httpx.Client(
    headers=SEC_HEADERS,
    timeout=httpx.Timeout(
        connect=10.0,
        read=60.0,
        write=30.0,
        pool=10.0,
    ),
    limits=httpx.Limits(
        max_connections=3,
        max_keepalive_connections=3,
    ),
    follow_redirects=True,
)

_RATE_LIMIT_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0


class SecProxyUnavailableError(ConnectionError):
    pass


class SecServiceUnavailableError(ConnectionError):
    pass


def wait_for_rate_limit() -> None:
    global _NEXT_REQUEST_AT

    interval = 1 / SEC_REQUESTS_PER_SECOND

    with _RATE_LIMIT_LOCK:
        now = time.monotonic()
        delay = max(0.0, _NEXT_REQUEST_AT - now)
        if delay:
            time.sleep(delay)
            now += delay
        _NEXT_REQUEST_AT = now + interval


def retry_delay(attempt: int, response: httpx.Response | None = None) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass

    return (2 ** attempt) + random.uniform(0.0, 0.25)


def _request_sec(
    method: str,
    url: str,
    *,
    max_retries: int,
    client: httpx.Client | None = None,
    **kwargs: Any,
) -> httpx.Response:
    request_client = client or SEC_CLIENT
    request = getattr(request_client, method.lower())

    for attempt in range(max_retries + 1):
        wait_for_rate_limit()

        try:
            response = request(url, **kwargs)
        except httpx.ProxyError as error:
            if attempt == max_retries:
                raise SecProxyUnavailableError(
                    f"SEC 请求代理不可用: {url}"
                ) from error
            time.sleep(retry_delay(attempt))
            continue
        except SEC_RETRYABLE_TRANSPORT_ERRORS:
            if attempt == max_retries:
                raise
            time.sleep(retry_delay(attempt))
            continue

        if response.status_code in SEC_RETRYABLE_STATUS_CODES:
            if attempt == max_retries:
                if response.status_code == 503:
                    raise SecServiceUnavailableError(
                        f"SEC 服务暂时不可用: {url}"
                    )
                response.raise_for_status()
            time.sleep(retry_delay(attempt, response))
            continue

        response.raise_for_status()
        return response

    raise AssertionError("unreachable")


def get_sec(
    url: str,
    *,
    client: httpx.Client | None = None,
    **kwargs: Any,
) -> httpx.Response:
    return _request_sec(
        "GET",
        url,
        max_retries=SEC_MAX_RETRIES,
        client=client,
        **kwargs,
    )


def post_sec(
    url: str,
    *,
    client: httpx.Client | None = None,
    **kwargs: Any,
) -> httpx.Response:
    return _request_sec(
        "POST",
        url,
        max_retries=0,
        client=client,
        **kwargs,
    )
