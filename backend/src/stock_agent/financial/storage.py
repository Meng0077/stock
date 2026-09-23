from datetime import date

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert

from stock_agent.financial.schemas import (
    FinancialFact,
)
from stock_agent.storage.tables import (
    financial_facts,
    financial_fact_syncs
)

def save_financial_facts(
    engine: Engine,
    facts: list[FinancialFact],
) -> int:
    """把标准化后的 FinancialFact 批量保存到 PostgreSQL。

    Args:
        engine:
            SQLAlchemy Engine。

            数据库连接由调用方创建并传入，
            这个函数不负责创建 Engine。

        facts:
            已经解析完成的 FinancialFact 列表。

            每条 fact 都必须已经拥有稳定的 fact_id。

    Returns:
        本次真正插入数据库的行数。

        如果某些 fact_id 已经存在，
        PostgreSQL 会跳过这些重复记录，
        因此返回值可能小于 len(facts)。

    这个函数负责：
        - FinancialFact -> 数据库 row。
        - 批量 INSERT。
        - 根据 fact_id 去重。

    这个函数不负责：
        - 请求 SEC。
        - 生成 fact_id。
        - as_of 过滤。
        - 判断季度 / 年度。
        - 更新 financial_fact_syncs。
    """

    # 空列表没有任何需要写入的数据，
    # 同时避免生成一个空的 INSERT statement。
    if not facts:
        return 0

    rows = [fact.model_dump() for fact in facts]
    statement = (
        insert(financial_facts)
        .values(rows )
        .on_conflict_do_nothing(index_elements=[
            financial_facts.c.fact_id
        ])
    )

    with engine.begin() as connection:
        result = connection.execute(statement)

    return result.rowcount

def query_financial_facts(
    engine,
    company_id,
    concept,
    unit,
    as_of,
) -> list[FinancialFact]:
    """从 PostgreSQL 查询指定财务事实。

    Args:
        engine:
            SQLAlchemy Engine。

        company_id:
            项目内部公司标识，例如 "NVDA"。

        concept:
            XBRL concept，例如 "NetIncomeLoss"。

        unit:
            数值单位，例如 "USD"。

        as_of:
            查询允许看到财务信息的最晚日期。

            只返回：
                filed_date <= as_of

            从而避免 historical 查询看到未来才提交的数据。

    Returns:
        符合条件的 FinancialFact 列表。

        结果按照：
            end_date
            filed_date

        从旧到新排列。

    这个函数负责：
        - 根据 company / concept / unit 查询数据库。
        - 在 SQL 层应用 as_of。
        - 把数据库 row 转回 FinancialFact。
        - 对结果进行稳定排序。

    这个函数不负责：
        - 请求 SEC。
        - 判断缓存是否足够新。
        - quarterly / annual / instant 筛选。
        - 更新同步状态。
    """
    statement = select(financial_facts).where(
        financial_facts.c.company_id == company_id,
        financial_facts.c.concept == concept,
        financial_facts.c.unit == unit,
        financial_facts.c.filed_date <= as_of,
    ).order_by(
        financial_facts.c.end_date,
        financial_facts.c.filed_date,
    )

    with engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()

    return [FinancialFact.model_validate(dict(row)) for row in rows]

def get_financial_fact_sync(
    engine: Engine,
    company_id: str,
    concept: str,
    unit: str,
) -> dict | None:
    """读取指定 Financial Facts 的同步状态。

    Args:
        engine:
            SQLAlchemy Engine。

        company_id:
            项目内部公司标识，例如 "NVDA"。

        concept:
            XBRL concept，例如 "NetIncomeLoss"。

        unit:
            财务事实单位，例如 "USD"。

    Returns:
        如果已经存在同步记录，返回类似：

            {
                "company_id": "NVDA",
                "concept": "NetIncomeLoss",
                "unit": "USD",
                "cik": "0001045810",
                "covered_through": date(...),
            }

        如果从未同步过，返回 None。

    这个函数负责：
        - 根据 company + concept + unit查询唯一的同步状态。

    这个函数不负责：
        - 判断缓存是否足够新。
        - 请求 SEC。
        - 更新同步状态。
    """

    statement = select(financial_fact_syncs).where(
        financial_fact_syncs.c.company_id == company_id,
        financial_fact_syncs.c.concept == concept,
        financial_fact_syncs.c.unit == unit,
    )

    with engine.connect() as connection:
        row = (
            connection.execute(statement)
            .mappings()
            .one_or_none()
        )

    if row is None:
        return None

    return dict(row)

def save_financial_fact_sync(
    engine: Engine,
    company_id: str,
    cik: str,
    concept: str,
    unit: str,
    covered_through: date,
) -> None:
    """保存或更新一组 Financial Facts 的同步状态。

    Args:
        engine:
            SQLAlchemy Engine。

        company_id:
            项目内部公司标识，例如 "NVDA"。

        cik:
            SEC CIK。

        concept:
            已完成同步的 XBRL concept。

        unit:
            已完成同步的单位，例如 "USD"。

        covered_through:
            表示这组数据已经检查 SEC 到哪个日期。

            例如：
                covered_through = date(2026, 9, 21)

            表示：
                截至 2026-09-21，
                已经成功检查过 SEC Company Facts。

    这个函数负责：
        - 第一次同步时 INSERT sync state。
        - 再次同步时更新 covered_through。

    这个函数不负责：
        - 请求 SEC。
        - 保存 FinancialFact。
        - 判断当前缓存是否需要刷新。
    """

    statement = insert(financial_fact_syncs).values(
            company_id=company_id,
            cik=cik,
            concept=concept,
            unit=unit,
            covered_through=covered_through,
        ).on_conflict_do_update(
            index_elements=[
                financial_fact_syncs.c.company_id,
                financial_fact_syncs.c.concept,
                financial_fact_syncs.c.unit,
            ],
            set_={
                "cik": cik,
                "covered_through": covered_through,
            },
        )
    with engine.begin() as connection:
        connection.execute(statement)

def get_financial_fact(
    engine: Engine,
    fact_id: str,
) -> FinancialFact | None:
    """根据 fact_id 查询一条 FinancialFact。

    Args:
        engine:
            SQLAlchemy Engine。

        fact_id:
            Financial Fact 的稳定 ID，例如：

                financial:98db11e9...

    Returns:
        找到时返回 FinancialFact。

        不存在时返回 None。

    这个函数负责：
        - 根据主键 fact_id 查询数据库。
        - 把数据库 row 转回 FinancialFact。

    这个函数不负责：
        - 判断 evidence_id 是否属于 financial 类型。
        - 请求 SEC。
        - 做 as_of 或 period filtering。
    """
    statement = select(financial_facts).where(
        financial_facts.c.fact_id == fact_id
    )

    with engine.connect() as connection:
        row = (
            connection.execute(statement)
            .mappings()
            .one_or_none()
        )

    if row is None:
        return None

    return FinancialFact.model_validate(
        dict(row)
    )
