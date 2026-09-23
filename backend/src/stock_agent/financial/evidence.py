from sqlalchemy import Engine

from stock_agent.financial.schemas import (
    FinancialFact,
)
from stock_agent.financial.storage import (
    get_financial_fact,
)


FINANCIAL_EVIDENCE_PREFIX = "financial:"


def is_financial_evidence_id(
    evidence_id: str,
) -> bool:
    """判断 evidence ID 是否属于 Financial Tool。

    Args:
        evidence_id:
            Agent 输出的 evidence ID。

    Returns:
        以 "financial:" 开头时返回 True。
    """
    return evidence_id.startswith(
        FINANCIAL_EVIDENCE_PREFIX
    )


def resolve_financial_evidence(
    engine: Engine,
    evidence_id: str,
) -> FinancialFact | None:
    """根据 financial evidence ID 找回原始 FinancialFact。

    Args:
        engine:
            SQLAlchemy Engine。

        evidence_id:
            Financial Tool 返回的 evidence ID。

            当前设计中：
                evidence_id == fact_id

    Returns:
        找到时返回 FinancialFact。

        如果 evidence_id 不是 financial 类型，
        或数据库中不存在对应 fact，
        返回 None。

    这个函数负责：
        evidence_id
            ↓
        fact_id
            ↓
        PostgreSQL
            ↓
        FinancialFact

    这个函数不负责：
        - 验证最终回答内容是否正确引用了该 fact。
        - 请求 SEC。
        - 生成新的 evidence ID。
    """

    if not is_financial_evidence_id(
        evidence_id
    ):
        return None

    return get_financial_fact(
        engine=engine,
        fact_id=evidence_id,
    )
