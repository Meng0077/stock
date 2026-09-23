from datetime import date
from typing import Literal
from sqlalchemy import Engine
import httpx

from stock_agent.financial.storage import (
    get_financial_fact_sync,
    save_financial_facts,
    save_financial_fact_sync,
    query_financial_facts
)
from stock_agent.documents.sec_provider import (
    UnknownTickerError,
    ticker_to_cik,
)
from stock_agent.financial.parsing import (
    # filter_facts_as_of,
    get_concept_entries,
    is_annual_duration_fact,
    is_instant_fact,
    is_quarterly_duration_fact,
    parse_financial_facts,
)
from stock_agent.financial.provider import (
    get_company_facts_json,
)
from stock_agent.financial.schemas import (
    FinancialFact,
)


FinancialPeriodType = Literal[
    "all",
    "quarterly",
    "annual",
    "instant",
]

def filter_financial_facts_by_period(
    facts: list[FinancialFact],
    period_type: FinancialPeriodType,
) -> list[FinancialFact]:
    """根据 period_type 筛选财务事实。

    Args:
        facts:
            已经完成 as_of 过滤的 FinancialFact。

        period_type:
            all / quarterly / annual / instant。

    Returns:
        符合指定期间类型的 facts。

    这个函数只负责期间类型筛选，
    不负责数据库查询或 as_of 判断。
    """

    if period_type == "quarterly":
        return [
            fact
            for fact in facts
            if is_quarterly_duration_fact(fact)
        ]

    if period_type == "annual":
        return [
            fact
            for fact in facts
            if is_annual_duration_fact(fact)
        ]

    if period_type == "instant":
        return [
            fact
            for fact in facts
            if is_instant_fact(fact)
        ]

    return facts

def sync_state_covers(
    sync_state: dict | None,
    as_of: date,
) -> bool:
    """判断已有同步状态是否足以覆盖当前 as_of。

    Args:
        sync_state:
            get_financial_fact_sync() 返回的同步状态。

            如果为 None，
            表示这个 concept + unit 从未成功同步。

        as_of:
            当前 Financial 查询的信息截止日期。

    Returns:
        True:
            已有同步结果足以覆盖当前 as_of，
            不需要再次请求 SEC。

        False:
            没有同步记录，或者已有同步范围不够，
            需要重新请求 SEC。

    这个函数只负责比较同步覆盖范围，
    不负责数据库查询或 SEC 请求。
    """
    if sync_state is None:
        return False


    return sync_state["covered_through"] >= as_of

def ensure_financial_facts_available(
    engine: Engine,
    client: httpx.Client,
    company_id: str,
    cik: str,
    concept: str,
    unit: str,
    as_of: date,
) -> None:
    """确保数据库已有足够回答当前查询的 Financial Facts。

    整体流程：
        1. 查看已有同步状态。
        2. 如果缓存覆盖当前 as_of，直接返回。
        3. 否则请求 SEC Company Facts。
        4. 提取并解析指定 concept + unit。
        5. 保存 FinancialFact。
        6. facts 保存成功后，最后更新 sync state。

    这个函数负责数据可用性，
    不负责返回最终查询结果。
    """

    # 查询当前 concept + unit 的同步状态。
    sync_state = get_financial_fact_sync(
        engine=engine,
        company_id=company_id,
        concept=concept,
        unit=unit,
    )

    # 如果已有数据足以覆盖 as_of，直接结束。
    if sync_state_covers(sync_state=sync_state, as_of=as_of):
        return

    # 缓存不够新，重新请求 SEC Company Facts。
    company_facts = get_company_facts_json(
        client=client,
        cik=cik,
    )

    # 只提取当前需要的 concept + unit。
    entries = get_concept_entries(
        company_facts=company_facts,
        concept=concept,
        unit=unit,
    )

    # SEC entry -> FinancialFact。
    facts = parse_financial_facts(
        company_id=company_id,
        concept=concept,
        unit=unit,
        entries=entries,
    )

    # 持久化。
    save_financial_facts(
        engine=engine,
        facts=facts,
    )

    # 数据和 facts 都成功写完后，
    # 最后再更新同步状态。
    save_financial_fact_sync(
        engine=engine,
        company_id=company_id,
        cik=cik,
        concept=concept,
        unit=unit,
        covered_through=date.today(),
    )

def select_latest_fact_per_period(
    facts: list[FinancialFact],
) -> list[FinancialFact]:
    """为每个财务期间选择最新披露版本。

    Args:
        facts:
            已经完成 as_of 和 period_type 过滤的 facts。

            同一个 start_date / end_date 可能因为后续 filing
            再次披露而出现多条记录。

    Returns:
        每个财务期间只保留一条 fact。

        当同一期间存在多个版本时，
        选择 filed_date 最晚的一条。

    为什么选择最新版本：
        query_financial_facts() 已经保证：
            filed_date <= as_of

        因此这里选出来的是：
            “截至 as_of，当时已知的最新版本”。

    这个函数不负责：
        - as_of 过滤。
        - quarterly / annual 判断。
        - 数据库存储。
    """

    latest_by_period: dict[
        tuple,
        FinancialFact,
    ] = {}

    for fact in facts:
        period_key = (
            fact.start_date,
            fact.end_date,
        )

        current = latest_by_period.get(
            period_key
        )

        if (
            current is None
            or fact.filed_date
            > current.filed_date
        ):
            latest_by_period[
                period_key
            ] = fact

    return sorted(
        latest_by_period.values(),
        key=lambda fact: (
            fact.end_date,
            fact.filed_date,
        ),
    )


def get_financial_facts(
    engine: Engine,
    client: httpx.Client,
    company_id: str,
    # cik: str,
    concept: str,
    unit: str,
    as_of: date,
    period_type: FinancialPeriodType = "all",
) -> list[FinancialFact]:
    """查询指定公司的结构化财务事实。

    这是 Financial 模块对外的主要业务入口。

    整体流程：
        1. 确保数据库已经拥有足够覆盖 as_of 的数据。
        2. 从 PostgreSQL 查询指定 concept + unit。
        3. 应用 as_of。
        4. 应用 quarterly / annual / instant 过滤。
        5. 返回 FinancialFact。

    调用方不需要知道：
        - 本次是否请求了 SEC。
        - 数据是否来自 PostgreSQL。
        - SEC Company Facts JSON 的具体结构。
    """

    company_id = company_id.upper()
    sync_state = get_financial_fact_sync(
        engine=engine,
        company_id=company_id,
        concept=concept,
        unit=unit,
    )

    if not sync_state_covers(sync_state, as_of):
        cik = ticker_to_cik(company_id)
        if cik is None:
            raise UnknownTickerError(company_id)

        ensure_financial_facts_available(
            engine=engine,
            client=client,
            company_id=company_id,
            cik=cik,
            concept=concept,
            unit=unit,
            as_of=as_of,
        )

    # 从 PostgreSQL 查询已经标准化的数据。
    facts = query_financial_facts(
        engine=engine,
        company_id=company_id,
        concept=concept,
        unit=unit,
        as_of=as_of,
    )

    facts = filter_financial_facts_by_period(
        facts=facts,
        period_type=period_type,
    )

    # 根据调用方想要的 period 类型进行确定性过滤。
    return select_latest_fact_per_period(facts)
