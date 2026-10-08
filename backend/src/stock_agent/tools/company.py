from stock_agent.documents.sec_provider import (
    UnknownTickerError,
    get_company_submissions,
    ticker_to_cik,
)
from stock_agent.tools.errors import UnsupportedCompanyError


COMPANY_PROFILE = {
    "company_id": "NVDA",
    "company_name": "NVIDIA（英伟达）",
    "description": "教学用简化公司介绍：提供 GPU 及相关计算平台，用于图形处理和人工智能计算。",
    "data_mode": "fixture",
    "source": "本地教学模拟数据",
    "as_of": "2026-09-11T09:00:00+08:00",
}


def get_company_profile(company_id: str) -> dict:
    """返回原有教学用公司资料，不访问网络。"""
    if company_id != "NVDA":
        raise UnsupportedCompanyError(
            f"不支持的公司标识：{company_id}"
        )
    return COMPANY_PROFILE.copy()


def get_sec_company_profile(
    company_id: str,
) -> dict:
    """
    从 SEC 获取公司的真实基础资料。

    数据流程：

        ticker
          ↓
        SEC ticker mapping
          ↓
        CIK
          ↓
        SEC submissions
          ↓
        company profile

    当前返回的是 SEC 当前提供的公司元数据，
    不是历史 point-in-time profile。
    """

    symbol = (
        company_id
        .strip()
        .upper()
    )

    cik = ticker_to_cik(
        symbol
    )

    if cik is None:
        raise UnknownTickerError(
            symbol
        )

    submissions = (
        get_company_submissions(
            cik=cik
        )
    )

    return {
        "company_id": symbol,
        "company_name": (
            submissions["name"]
        ),
        "cik": cik,

        "tickers": (
            submissions.get(
                "tickers",
                [],
            )
        ),

        "exchanges": (
            submissions.get(
                "exchanges",
                [],
            )
        ),

        "sic": (
            submissions.get(
                "sic"
            )
        ),

        "sic_description": (
            submissions.get(
                "sicDescription"
            )
        ),

        "entity_type": (
            submissions.get(
                "entityType"
            )
        ),

        "fiscal_year_end": (
            submissions.get(
                "fiscalYearEnd"
            )
        ),

        "state_of_incorporation": (
            submissions.get(
                "stateOfIncorporation"
            )
        ),

        "website": (
            submissions.get(
                "website"
            )
        ),

        "investor_website": (
            submissions.get(
                "investorWebsite"
            )
        ),

        "description": (
            submissions.get(
                "description"
            )
        ),

        "data_mode": "live",
        "source": "SEC submissions",
    }
