from collections.abc import Sequence
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


# 8-K 不一定都是财报。
#
# 历史财报研究时先最多取这些候选 8-K，
# 然后逐个判断是否包含 Item 2.02。
#
# 找够用户要求的 Earnings Event 后会提前停止，
# 不会把全部候选都加载一遍。
EARNINGS_8K_SCAN_LIMIT = 100

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

@dataclass(frozen=True)
class EarningsReactionEntry:
    """
    一次 Earnings Event 及其对应市场反应。

    保留 EarningsReleaseEvent，
    是为了让上层除了 reaction 之外，
    仍然能够看到：
    - report_date
    - accession number
    - SEC source URL
    - event time warning
    """
    earnings: EarningsReleaseEvent
    reaction: MarketReactionResult

@dataclass(frozen=True)
class HistoricalEarningsReaction:
    """
    某只股票最近若干次财报披露后的市场反应。
    """
    symbol: str

    # 严格历史边界。
    # 只研究 event.released_at < before 的事件。
    before: datetime
    as_of: datetime

    events: list[EarningsReactionEntry]
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

def _build_earnings_release_event(
    *,
    symbol: str,
    filing: FilingMetadata,
) -> EarningsReleaseEvent:
    """
    把已确认属于 Earnings 的 8-K
    转成统一 EarningsReleaseEvent。

    这里不判断 filing 是否真的是 Earnings；
    调用方必须已经通过 is_earnings_8k()。
    """

    return EarningsReleaseEvent(
        event_id=(
            f"earnings:"
            f"{symbol}:"
            f"{filing.accession_number}"
        ),
        symbol=symbol,
        released_at=filing.accepted_at,
        released_at_source=(
            "sec_8k_accepted_at"
        ),
        report_date=filing.report_date,
        accession_number=(
            filing.accession_number
        ),
        source_url=filing.document_url,
        warnings=(
            "event_time_uses_sec_8k_acceptance",
        ),
    )

def get_earnings_releases(
    *,
    symbol: str,
    as_of: datetime,
    limit: int,
    before: datetime | None = None,
) -> list[EarningsReleaseEvent]:
    """
    获取截至 as_of 可见的最近 N 次 Earnings 8-K。

    如果提供 before：
    只返回 released_at < before 的事件。

    as_of：
    数据可见边界。

    before：
    业务上的严格历史边界。
    """

    if (
        before is not None
        and (
            before.tzinfo is None
            or before.utcoffset() is None
        )
    ):
        raise ValueError("before must be timezone-aware")

    if (
        as_of.tzinfo is None
        or as_of.utcoffset() is None
    ):
        raise ValueError("as_of must be timezone-aware")

    if limit <= 0:
        raise ValueError("limit must be positive")

    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol must not be empty")
    filings = get_recent_filings(
        company_id=normalized_symbol,
        as_of=as_of,
        limit=EARNINGS_8K_SCAN_LIMIT,
        forms={"8-K"},
    )

    releases: list[EarningsReleaseEvent] = []
    for filing in filings:

        if before is not None and filing.accepted_at >= before:
            continue

        if not is_earnings_8k(filing):
            continue

        release = _build_earnings_release_event(symbol=normalized_symbol, filing=filing)
        releases.append(release)
        if len(releases) >= limit:
            break

    return releases

def get_latest_earnings_release(
    *,
    symbol: str,
    as_of: datetime,
) -> EarningsReleaseEvent | None:
    """
    获取 as_of 之前最近一次可确认的 Earnings 8-K。
    """
    release = get_earnings_releases(
        symbol=symbol,
        as_of=as_of,
        limit=1,
    )
    if not release:
        return None
    return release[0]

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

def research_earnings_reactions(
    *,
    earnings: Sequence[EarningsReleaseEvent],
    symbol: str,
    provider: MarketDataProvider,
    as_of: datetime,
) -> list[MarketReactionResult]:
    """
    对一组已经选定的 Earnings Event
    分别计算市场反应。

    本函数不负责：
    - 查 SEC；
    - 选择最近几次财报；
    - 判断 latest / history；
    - 处理 before / limit。

    Event selection 由上层完成。
    """
    results: list[MarketReactionResult] = []

    for earning in earnings:
        reaction = research_earnings_reaction(
            earnings=earning,
            symbol=symbol,
            provider=provider,
            as_of=as_of,
        )
        results.append(reaction)
    return results
