from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from collections.abc import Callable
from typing import Protocol, runtime_checkable

import httpx

from stock_agent.documents.sec_http import (
    SecProxyUnavailableError,
    SecServiceUnavailableError,
)
from stock_agent.market.errors import (
    MarketDataProviderError,
)
from stock_agent.market.schemas import (
    SecurityInfo,
)

from stock_agent.documents.sec_http import (
    get_sec,
)

SEC_TICKERS_URL = (
    "https://www.sec.gov/files/company_tickers.json"
)


@dataclass(frozen=True)
class SecurityRecord:
    """
    系统已经确认存在的证券标的。

    symbol:
        系统内部使用的 ticker。

    name:
        SEC 或行情源提供的证券名称。

    cik:
        SEC issuer CIK。

        ETF 等证券可能没有当前系统可用的 CIK，
        因此允许为 None。
    """

    symbol: str
    name: str
    cik: str | None

def build_sec_security_index(
    payload: dict[str, Any],
) -> dict[str, SecurityRecord]:
    """
    把 SEC company_tickers.json
    转成 ticker -> SecurityRecord 索引。

    这里是纯转换函数：
    不发送网络请求，
    方便独立测试 SEC payload 处理逻辑。
    """
    securities: dict[str, SecurityRecord] = {}
    for item in payload.values():
        key = str(item["ticker"]).strip().upper()
        cik = str(item["cik_str"]).zfill(10)
        name = str(item["title"]).strip()

        securities[key] = SecurityRecord(
            symbol=key,
            name=name,
            cik=cik,
        )
    return securities

@lru_cache(maxsize=1)
def load_sec_security_index(
) -> dict[str, SecurityRecord]:
    """
    加载并缓存 SEC ticker / CIK 索引。

    company_tickers.json 在一次进程生命周期内
    不需要为每个用户问题重复下载。
    """

    response = get_sec(SEC_TICKERS_URL)

    payload = response.json()

    return build_sec_security_index(
        payload
    )

def find_sec_security(
    symbol: str,
) -> SecurityRecord | None:
    """
    根据 ticker 查询 SEC issuer identity。

    找到：
        返回 SecurityRecord。

    找不到：
        返回 None。

    SEC 请求失败：
        不在这里伪装成 None，
        让异常继续向上交给 Registry 处理。
    """
    n_symbol = symbol.strip().upper()

    if not n_symbol:
        raise ValueError("symbol must not be empty")
    securities = load_sec_security_index()

    return securities.get(n_symbol)

@runtime_checkable
class SecurityLookupProvider(Protocol):
    """
    Security Registry 需要的最小行情源能力。

    不要求完整 MarketDataProvider，
    只要求能够验证证券 symbol。
    """
    def get_security_info(
        self,
        symbol: str,
    ) -> SecurityInfo | None:
        ...


class SecurityRegistryUnavailableError(
    RuntimeError
):
    """
    当前无法可靠完成证券存在性验证。

    这和 ticker 不存在是两个不同状态。
    """

    pass

def lookup_security(
    symbol: str,
    *,
    fallback_provider_factory: (
        Callable[[], object] | None
    ),
) -> SecurityRecord | None:
    """
    验证并解析一个 candidate ticker。

    查询顺序：

    1. SEC ticker index；
    2. SEC 没找到或暂时不可用时，
       使用支持 Security Lookup 的行情源；
    3. 两个数据源都确认没有时返回 None；
    4. 无法可靠执行 fallback 时，
       抛出 SecurityRegistryUnavailableError。

    SEC 命中时同时得到 CIK；
    只有行情源命中时 cik=None。
    """
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol must not be empty")

    try:
        sec_security = find_sec_security(normalized_symbol)
    except (SecProxyUnavailableError, SecServiceUnavailableError, httpx.HTTPError):
        sec_security = None

    if sec_security is not None:
        return sec_security

    if fallback_provider_factory is None:
        raise SecurityRegistryUnavailableError(
            "security fallback provider "
            "is not configured"
        )

    provider = fallback_provider_factory()
    if not isinstance(provider, SecurityLookupProvider):
        raise SecurityRegistryUnavailableError(
            "configured market provider "
            "does not support security lookup"
        )

    try:
        market_security = provider.get_security_info(normalized_symbol)
    except MarketDataProviderError as exc:
        raise SecurityRegistryUnavailableError(
            "security lookup provider "
            "is unavailable"
        ) from exc

    if market_security is None:
        return None


    return SecurityRecord(
        symbol=market_security.symbol,
        name=market_security.name,
        cik=None
    )
