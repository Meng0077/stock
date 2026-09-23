from datetime import date
from typing import Any

from stock_agent.financial.identity import build_financial_fact_id
from stock_agent.financial.schemas import FinancialFact

def get_concept_entries(
    company_facts: dict[str, Any],
    concept: str,
    unit: str,
    taxonomy: str = "us-gaap",
) -> list[dict[str, Any]]:
    """从 Company Facts JSON 中读取指定 concept 和 unit 的原始记录。

    Args:
        company_facts:
            get_company_facts_json() 返回的原始 SEC JSON。

        concept:
            XBRL concept 名称，例如：
            "NetIncomeLoss"
            "Assets"
            "RevenueFromContractWithCustomerExcludingAssessedTax"

        unit:
            数值单位，例如：
            "USD"
            "shares"
            "USD/shares"

        taxonomy:
            XBRL taxonomy。
            第一版默认使用 "us-gaap"。

    Returns:
        SEC 对这个 concept + unit 返回的原始 fact entries。

        如果 taxonomy、concept 或 unit 不存在，
        返回空列表。

    这个函数负责：
        - 在 Company Facts JSON 中定位 concept。
        - 根据 unit 取得原始 entries。

    这个函数不负责：
        - 判断最新季度。
        - as_of 过滤。
        - 10-Q / 10-K 筛选。
        - 转换成 FinancialFact。
    """

    facts = company_facts.get("facts", {})
    taxonomy_facts = facts.get(taxonomy, {})
    concept_data = taxonomy_facts.get(concept)
    if concept_data is None:
        return []
    units = concept_data.get("units", {})
    return units.get(unit, [])


def parse_financial_fact(
    company_id: str,
    concept: str,
    unit: str,
    entry: dict[str, Any],
) -> FinancialFact:
    """把 SEC Company Facts 中的一条原始 entry 转成 FinancialFact。

    Args:
        company_id:
            项目内部使用的公司标识，例如 "NVDA"。

        concept:
            当前 entry 所属的 XBRL concept，例如：
            "NetIncomeLoss"
            "Assets"

        unit:
            当前 entry 使用的单位，例如：
            "USD"
            "shares"

        entry:
            SEC Company Facts 返回的一条原始记录。

            常见结构例如：
            {
                "start": "2026-01-26",
                "end": "2026-04-26",
                "val": 18775000000,
                "accn": "0001045810-26-...",
                "form": "10-Q",
                "filed": "2026-05-...",
                ...
            }

    Returns:
        带稳定 fact_id 的 FinancialFact。

    这个函数负责：
        - 字段映射。
        - 日期转换。
        - 保存 SEC fiscal metadata。

    这个函数不负责：
        - as_of 过滤。
        - 判断季度 / 年度。
        - 从重复事实中选择最终值。
    """

    start = entry.get("start")

    fact_id = build_financial_fact_id(
        company_id,
        concept,
        unit,
        entry
    )

    return FinancialFact(
        fact_id=fact_id,
        company_id=company_id,
        concept=concept,
        value=entry["val"],
        unit=unit,
        start_date=date.fromisoformat(start) if start is not None else None,
        end_date=date.fromisoformat(entry["end"]),
        filed_date=date.fromisoformat(entry["filed"]),
        form=entry["form"],
        accession_number=entry["accn"],
        fiscal_year=entry.get("fy"),
        fiscal_period=entry.get("fp"),
        frame=entry.get("frame"),
    )


def parse_financial_facts(
    company_id: str,
    concept: str,
    unit: str,
    entries: list[dict[str, Any]],
) -> list[FinancialFact]:
    """把同一个 concept + unit 下的多条 SEC entries 批量转换。

    Args:
        company_id:
            项目内部公司标识。

        concept:
            XBRL concept。

        unit:
            财务数据单位。

        entries:
            get_concept_entries() 返回的原始 SEC entries。

    Returns:
        转换后的 FinancialFact 列表。

    这个函数只负责批量调用 parse_financial_fact()，
    不负责筛选或排序。
    """

    return [
        parse_financial_fact(
            company_id=company_id,
            concept=concept,
            unit=unit,
            entry=entry,
        )
        for entry in entries
    ]


def filter_facts_as_of(
    facts: list[FinancialFact],
    as_of: date,
) -> list[FinancialFact]:
    """过滤出在指定日期时已经公开申报的财务事实。

    Args:
        facts:
            已经转换完成的 FinancialFact 列表。

        as_of:
            查询允许使用财务信息的最晚日期。

            例如：
                as_of = date(2026, 8, 20)

            表示只能使用 filed_date <= 2026-08-20
            的财务事实。

    Returns:
        filed_date 不晚于 as_of 的 FinancialFact 列表。

    这个函数负责：
        - 防止使用 as_of 之后才提交的财务数据。

    这个函数不负责：
        - 判断季度 / 年度。
        - 判断哪条 fact 是最新值。
        - 去重。
        - 计算同比、环比或 TTM。
        - 判断 SEC filing 的精确 accepted_at 时间。

    注意：
        当前 Company Facts 数据只使用 filed_date，
        因此这是“日期级”的历史过滤，
        不是精确到时分秒的 point-in-time 过滤。
    """
    return [
        fact for fact in facts
        if fact.filed_date <= as_of
    ]


def is_instant_fact(
    fact: FinancialFact,
) -> bool:
    """判断一条 FinancialFact 是否是时点型事实。

    Args:
        fact:
            一条标准化 FinancialFact。

    Returns:
        start_date 为空时返回 True。

    典型 instant fact：
        - Assets
        - Liabilities
        - CashAndCashEquivalentsAtCarryingValue

    它们表达的是：
        “某个日期公司的余额是多少”

    而不是：
        “一段期间内发生了多少”

    这个函数只判断事实形态，
    不判断 concept 本身的业务含义。
    """

    return fact.start_date is None


def get_fact_duration_days(
    fact: FinancialFact,
) -> int | None:
    """计算 duration fact 覆盖了多少天。

    Args:
        fact:
            一条 FinancialFact。

    Returns:
        duration fact 返回 start_date 到 end_date 的天数；
        instant fact 返回 None。

    这个函数负责：
        - 提供一个简单的期间长度指标。

    这个函数不负责：
        - 判断季度或年度。
    """
    if fact.start_date is None:
        return None

    return (fact.end_date - fact.start_date).days + 1


def is_quarterly_duration_fact(
    fact: FinancialFact,
) -> bool:
    """判断一条 duration fact 是否近似代表单个季度。

    Args:
        fact:
            一条 FinancialFact。

    Returns:
        同时满足以下条件时返回 True：
        - 来自 10-Q；
        - 有 start_date；
        - 期间长度约为一个季度。

    为什么不能只看 form == "10-Q"：
        Q2 的 10-Q 可能同时包含：
            三个月数据
            六个月 YTD 数据

        两者 form 都是 10-Q。

    当前第一版使用 70～110 天作为季度期间范围。

    这个函数不负责：
        - 处理异常财政周期。
        - 处理所有 SEC XBRL 特殊情况。
        - 判断是不是“最新季度”。
    """

    if fact.form not in {"10-Q", "10-Q/A"}:
        return False

    duration_days = get_fact_duration_days(
        fact
    )
    if duration_days is None:
        return False

    return 70 <= duration_days <= 110


def is_annual_duration_fact(
    fact: FinancialFact,
) -> bool:
    """判断一条 duration fact 是否近似代表完整财年。

    Args:
        fact:
            一条 FinancialFact。

    Returns:
        同时满足以下条件时返回 True：
        - 来自 10-K；
        - 有 start_date；
        - 覆盖时间接近完整一年。

    当前第一版使用 330～380 天作为年度范围。

    这个函数不负责：
        - 判断最新年度。
        - 处理特殊的超长/超短财政年度。
    """

    if fact.form not in {"10-K", "10-K/A"}:
        return False

    duration_days = get_fact_duration_days(
        fact
    )

    if duration_days is None:
        return False

    return 330 <= duration_days <= 380
