from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class FinancialFact(BaseModel):
    """表示一条已经标准化的 SEC XBRL 财务事实。

    这个模型负责：
        - 保存财务数值及其单位。
        - 保存事实对应的报告期间。
        - 保存来源 filing 信息。
        - 保留 SEC 的 fiscal period / frame 信息，供后续判断季度、年度等语义。

    这个模型不负责：
        - 判断哪条 fact 是最终要返回给用户的值。
        - 计算同比、环比、TTM。
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    # 该 fact 在项目中的稳定身份。
    #
    # 同时作为：
    # - PostgreSQL primary key
    # - Agent financial evidence_id
    fact_id: str

    company_id: str

    # XBRL concept 名称，例如：
    # RevenueFromContractWithCustomerExcludingAssessedTax
    # NetIncomeLoss
    # Assets
    concept: str

    # 财务事实的实际数值。
    value: Decimal

    unit: str

    # Duration fact 的起始日期。
    # Revenue / NetIncome 这种“一个期间”的指标通常有 start_date。
    # Assets 这种“某个时点”的指标通常没有 start_date。
    start_date: date | None = None

    # 财务事实对应期间的结束日期，或者 instant fact 的时点。
    end_date: date

    # 这条 fact 所属 filing 向 SEC 提交的日期。
    filed_date: date

    form: str

    # SEC filing 的 accession number。
    accession_number: str

    # SEC 的 fiscal year，例如 2026。
    # 某些 entry 可能没有，所以允许 None。
    fiscal_year: int | None = None

    # SEC fiscal period，例如：
    # Q1 / Q2 / Q3 / FY。
    fiscal_period: str | None = None

    # SEC frame，例如：
    # CY2026Q1
    # CY2026
    #
    # 并不是每一条 Company Facts entry 都有 frame。
    frame: str | None = None
