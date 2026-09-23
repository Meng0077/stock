"""验证 Financial Facts 可以跨 Python 进程复用 PostgreSQL 数据。

运行方式：

第一次运行：

    PYTHONPATH=backend/src backend/.venv/bin/python \
        evals/verify_financial_persistence.py --phase seed

第二次运行：

    PYTHONPATH=backend/src backend/.venv/bin/python \
        evals/verify_financial_persistence.py --phase reuse

seed：
    允许访问 SEC，并把 Financial Facts 持久化到数据库。

reuse：
    使用一个“任何 HTTP 请求都会报错”的 client。
    如果仍然能够返回结果，说明数据真正来自 PostgreSQL。
"""

import argparse
from collections import Counter
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv

from stock_agent.financial.service import (
    get_financial_facts,
)

from stock_agent.storage.database import (
    create_database_engine,
)

from stock_agent.documents.sec_http import SEC_CLIENT


ROOT = Path(__file__).resolve().parents[1]

def verify_seed() -> None:
    """首次查询 Financial Facts，并写入 PostgreSQL。

    这个阶段允许真实访问 SEC。

    验收目标：
        - get_financial_facts() 能正常返回数据。
        - ensure 流程会请求 SEC。
        - FinancialFact 会写入 PostgreSQL。
        - financial_fact_syncs 会留下完成凭证。
    """

    engine = create_database_engine()

    facts = get_financial_facts(
        engine=engine,
        client=SEC_CLIENT,
        company_id="NVDA",
        # cik="1045810",
        concept="NetIncomeLoss",
        unit="USD",
        as_of=date(2026, 9, 20),
        period_type="quarterly",
    )

    assert facts, (
        "seed 阶段没有查询到任何 FinancialFact"
    )

    print(
        "seed completed:",
        len(facts),
        "facts",
    )

    periods = [
        (
            fact.start_date,
            fact.end_date,
        )
        for fact in facts
    ]

    counts = Counter(periods)

    duplicates = {
        period: count
        for period, count in counts.items()
        if count > 1
    }

    print(
        "total facts:",
        len(facts),
    )

    print(
        "unique periods:",
        len(counts),
    )

    print(
        "duplicate periods:",
        len(duplicates),
    )

    for period, count in list(
        duplicates.items()
    )[-10:]:
        print(
            period,
            count,
        )

    for fact in facts[-10:]:
        print(
            "period:",
            fact.start_date,
            "->",
            fact.end_date,
            "value:",
            fact.value,
            "form:",
            fact.form,
            "fp:",
            fact.fiscal_period,
            "frame:",
            fact.frame,
            "filed:",
            fact.filed_date,
            "accn:",
            fact.accession_number,
        )

def fail_on_request(
    request: httpx.Request,
) -> httpx.Response:
    """拒绝所有 HTTP 请求。

    reuse 阶段如果 Financial service 仍尝试访问 SEC，
    测试应该立即失败。
    """

    raise AssertionError(
        "reuse 阶段不应该访问 SEC："
        f"{request.method} {request.url}"
    )

def build_failing_client() -> httpx.Client:
    """创建一个任何 HTTP 请求都会失败的 httpx.Client。

    Returns:
        配置了 MockTransport 的 Client。

    这个 client 的目的不是模拟 SEC 返回值，
    而是证明 reuse 阶段根本没有发生网络请求。
    """

    transport = httpx.MockTransport(
        fail_on_request
    )

    return httpx.Client(
        transport=transport,
    )

def verify_reuse() -> None:
    """验证新 Python 进程可以直接复用 PostgreSQL。

    这个阶段禁止任何 HTTP 请求。

    如果查询仍然成功，说明：
        - sync state 已经持久化；
        - FinancialFact 已经持久化；
        - ensure 判断缓存足够；
        - service 直接从 PostgreSQL 返回结果。
    """

    engine = create_database_engine()

    client = build_failing_client()

    try:
        facts = get_financial_facts(
            engine=engine,
            client=client,
            company_id="NVDA",
            # cik="1045810",
            concept="NetIncomeLoss",
            unit="USD",
            as_of=date(2026, 9, 20),
            period_type="quarterly",
        )
    finally:
        client.close()

    assert facts, (
        "reuse 阶段没有从数据库查询到 FinancialFact"
    )

    print(
        "reuse completed:",
        len(facts),
        "facts",
    )

    for fact in facts[-3:]:
        print(
            fact.end_date,
            fact.value,
            fact.fact_id,
        )


def main() -> None:
    """根据命令行参数执行 seed 或 reuse 验收。"""

    load_dotenv(ROOT / "backend" / ".env", override=False)

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--phase",
        choices=[
            "seed",
            "reuse",
        ],
        required=True,
    )

    args = parser.parse_args()

    if args.phase == "seed":
        verify_seed()
        return

    verify_reuse()


if __name__ == "__main__":
    main()
