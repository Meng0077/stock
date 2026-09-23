from typing import Any

import httpx

from stock_agent.documents.sec_http import get_sec

SEC_COMPANY_FACTS_URL = (
    "https://data.sec.gov/api/xbrl/companyfacts"
)


def build_company_facts_url(
    cik: str,
) -> str:
    """构造 SEC Company Facts API URL。

    Args:
        cik:
            SEC CIK。
            可以传 "1045810"，也可以传 "0001045810"。

    Returns:
        SEC Company Facts API 的完整请求地址。

    这个函数负责：
        - 把 CIK 补齐为 SEC API 要求的 10 位格式。
        - 构造 URL。

    这个函数不负责：
        - 发送 HTTP 请求。
        - 校验公司是否存在。
        - 解析任何财务数据。
    """
    normalized_cik = cik.zfill(10)
    return (
        f"{SEC_COMPANY_FACTS_URL}/"
        f"CIK{normalized_cik}.json"
    )


def get_company_facts_json(
    client: httpx.Client,
    cik: str,
) -> dict[str, Any]:
    """下载某公司的原始 Company Facts JSON。

    Args:
        cik:
            SEC CIK。

    Returns:
        SEC 返回的原始 JSON。

    负责网络获取，不负责财务 fact 解析。
    """

    url = build_company_facts_url(cik)

    response = get_sec(
        url,
        client=client,
    )

    return response.json()
