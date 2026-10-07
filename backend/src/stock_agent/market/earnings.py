from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from stock_agent.documents.schemas import (
    FilingMetadata,
)
from stock_agent.documents.sec_loader import (
    load_filing_document,
)
from stock_agent.documents.sec_provider import (
    get_filing_files,
    get_recent_filings,
)
from stock_agent.market.provider import (
    MarketDataProvider,
)
from stock_agent.market_reaction.models import (
    MarketReactionResult,
)
from stock_agent.market_reaction.service import (
    research_timed_event_reaction,
)


@dataclass(frozen=True)
class EarningsReleaseEvent:
    """
    一次可用于市场反应研究的财报披露事件。

    当前第一版使用 SEC 8-K Item 2.02
    的 acceptance timestamp 作为公开事件时间。

    注意：
    该时间代表 SEC 接收并公开 filing 的时间，
    不保证一定等于公司新闻稿最早对外发布时间。
    """

    event_id: str
    symbol: str

    released_at: datetime
    released_at_source: Literal[
        "sec_8k_accepted_at"
    ]

    report_date: date | None

    accession_number: str
    source_url: str

    warnings: tuple[str, ...] = ()


def is_earnings_8k(
    filing: FilingMetadata,
) -> bool:
    """
    判断一份 8-K 是否属于业绩披露。

    第一版只认 SEC Item 2.02：
    Results of Operations and Financial Condition。
    """
    if filing.form != "8-K":
        return False

    files = get_filing_files(filing=filing)
    primary_file = next(
        (
            file
            for file in files
            if file.is_primary
        ),
        None,
    )

    if primary_file is None:
        return False

    document = load_filing_document(
        filing=filing,
        filing_file=primary_file,
    )
    content = document.content.lower()

    return (
        "item 2.02" in content
        or
        (
            "results of operations"
            " and financial condition"
        )
        in content
    )


def get_latest_earnings_release(
    *,
    symbol: str,
    as_of: datetime,
) -> EarningsReleaseEvent | None:
    """
    获取 as_of 之前最近一次可确认的 Earnings 8-K。
    """
    normalized_symbol = symbol.strip().upper()

    # 不能默认最近几个 8-K 都是财报，
    # 稍微多取一些再筛 Item 2.02。
    filings = get_recent_filings(
        normalized_symbol,
        as_of,
        forms={"8-K"},
        limit=20,
    )

    for filing in filings:
        if not is_earnings_8k(filing):
            continue
        return EarningsReleaseEvent(
            event_id=f"earnings:{normalized_symbol}:{filing.accession_number}",
            symbol=normalized_symbol,
            released_at=filing.accepted_at,
            released_at_source="sec_8k_accepted_at",
            report_date=filing.report_date,
            accession_number=filing.accession_number,
            source_url=filing.document_url,
            warnings=(
                "event_time_uses_sec_8k_acceptance",
            ),
        )
    return None


def research_earnings_reaction(
    *,
    earnings: EarningsReleaseEvent,
    symbol: str,
    provider: MarketDataProvider,
    as_of: datetime,
) -> MarketReactionResult:
    """
    研究一次已确认 Earnings 8-K 公布后的市场反应。

    当前 event_at 使用 SEC 8-K accepted_at。
    """
    return research_timed_event_reaction(
        event_id=earnings.event_id,
        event_type="earnings",
        event_at=earnings.released_at,
        event_time_source=earnings.released_at_source,
        symbol=symbol,
        provider=provider,
        as_of=as_of,
        extra_issues=list(earnings.warnings),
    )
