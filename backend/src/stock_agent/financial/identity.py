import hashlib
import json
from typing import Any


def build_financial_fact_id(
    company_id: str,
    concept: str,
    unit: str,
    entry: dict[str, Any],
) -> str:
    """为一条 SEC Company Facts entry 构造稳定的 fact ID。

    Args:
        company_id:
            项目内部公司标识，例如 "NVDA"。

        concept:
            XBRL concept，例如 "NetIncomeLoss"。

        unit:
            SEC fact 的单位，例如 "USD"。

        entry:
            SEC Company Facts 返回的一条原始 fact entry。

            这里会使用：
                - accn
                - start
                - end
                - val

            来区分同一 filing 中不同期间或不同数值的 fact。

    Returns:
        稳定的 Financial Fact ID，例如：

            financial:2ab134...

    这个函数负责：
        - 根据 fact 的源数据身份构造确定性 ID。
        - 相同源 fact 每次都生成相同 ID。
        - 不同期间 / 数值的 fact 生成不同 ID。

    这个函数不负责：
        - 判断季度、年度或 instant。
        - 持久化数据库。
        - 验证 SEC entry 是否适合当前查询。
    """

    identity = {
        "company_id": company_id,
        "concept": concept,
        "unit": unit,
        "accession_number": entry["accn"],

        # instant fact 没有 start，
        # 使用 None 也可以稳定参与 JSON 序列化。
        "start": entry.get("start"),

        "end": entry["end"],

        # 这里直接使用 SEC 原始 val，
        # 而不是已经转成 float 的 FinancialFact.value。
        "value": entry["val"],
    }

    canonical = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    digest = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    return f"financial:{digest}"
