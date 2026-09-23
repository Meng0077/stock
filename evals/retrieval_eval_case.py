from datetime import datetime
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

class RetrievalEvalCase(BaseModel):
    """一条 Filing retrieval 的人工标注评估案例。

    字段含义：
        case_id:
            稳定的案例 ID。

        split:
            dev 用于开发和调参数；
            holdout 只用于最后验证，避免针对测试集调参。

        company_id:
            公司标识，例如 NVDA。

        question:
            用户原始问题。
            可以是中文，也可以是英文。

        as_of:
            该问题允许使用信息的最大时间。
            检索必须遵守 point-in-time 约束。

        required_block_ids:
            人工确认能够支持该问题的 FilingBlock ID。
            Retriever 返回的 chunk 只要覆盖这些 block，
            就认为命中了对应 evidence。

    本模型不保存：
        - chunk_id：它依赖 chunk 配置，不够稳定；
        - expected answer：D19 只评 retrieval；
        - retrieval score：那是运行结果，不属于 case 定义。
    """

    model_config = ConfigDict(
        extra="forbid",
    )

    case_id: str

    split: Literal[
        "dev",
        "holdout",
    ]

    company_id: str

    question: str

    as_of: datetime

    required_block_ids: list[str]

CASES_DEV = [
    {"case_id":"NVDA-001","split":"dev","company_id":"NVDA","question":"NVDA 最近一个季度数据中心业务增长的主要原因是什么？","as_of":"2026-09-22T16:00:00+08:00","required_block_ids":[]},
    {"case_id":"NVDA-002","split":"dev","company_id":"NVDA","question":"NVIDIA 在最近季度对中国相关出口限制披露了哪些风险？","as_of":"2026-09-22T16:00:00+08:00","required_block_ids":[]},
    {"case_id":"NVDA-003","split":"dev","company_id":"NVDA","question":"NVDA 最近季度毛利率变化的主要原因是什么？","as_of":"2026-09-22T16:00:00+08:00","required_block_ids":[]},
    {"case_id":"NVDA-004","split":"dev","company_id":"NVDA","question":"NVIDIA 最近季度游戏业务收入变化的原因是什么？","as_of":"2026-09-22T16:00:00+08:00","required_block_ids":[]},
    {"case_id":"NVDA-005","split":"dev","company_id":"NVDA","question":"管理层如何描述 Blackwell 产品的需求和供给情况？","as_of":"2026-09-22T16:00:00+08:00","required_block_ids":[]},
    {"case_id":"NVDA-006","split":"dev","company_id":"NVDA","question":"NVIDIA 最近季度是否提到供应链或产能限制？具体是什么？","as_of":"2026-09-22T16:00:00+08:00","required_block_ids":[]},
    {"case_id":"NVDA-007","split":"dev","company_id":"NVDA","question":"What factors did NVIDIA identify as risks to its data center business?","as_of":"2026-09-22T16:00:00+08:00","required_block_ids":[]},
    {"case_id":"NVDA-008","split":"holdout","company_id":"NVDA","question":"NVIDIA 如何解释最近季度营业费用的变化？","as_of":"2026-09-22T16:00:00+08:00","required_block_ids":[]},
    {"case_id":"NVDA-009","split":"holdout","company_id":"NVDA","question":"What did NVIDIA say about customer concentration or dependence on major customers?","as_of":"2026-09-22T16:00:00+08:00","required_block_ids":[]},
    {"case_id":"NVDA-010","split":"holdout","company_id":"NVDA","question":"NVIDIA 最近一期 10-Q 中对 AI 基础设施需求的描述是什么？","as_of":"2026-09-22T16:00:00+08:00","required_block_ids":[]},
]

def load_retrieval_eval_cases(
    path: Path,
) -> list[RetrievalEvalCase]:
    """从 JSONL 文件加载 retrieval eval cases。

    Args:
        path:
            JSONL 文件路径。

    Returns:
        已经过 Pydantic 校验的 RetrievalEvalCase 列表。

    Raises:
        ValueError:
            JSON 行非法或 case_id 重复时抛出。

    本函数只负责：
        - JSONL 解析；
        - Pydantic 校验；
        - case_id 唯一性检查。

    不负责：
        - 构建索引；
        - 验证 block_id 是否存在；
        - 执行 retrieval。
    """

    cases: list[RetrievalEvalCase] = []
    case_ids: set[str] = set()

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        for line_number, line in enumerate(
            file,
            start=1,
        ):
            line = line.strip()

            if not line:
                continue

            try:
                data = json.loads(line)

                case = (
                    RetrievalEvalCase.model_validate(
                        data
                    )
                )

            except Exception as exc:
                raise ValueError(
                    f"invalid eval case "
                    f"at line {line_number}"
                ) from exc

            if case.case_id in case_ids:
                raise ValueError(
                    "duplicate case_id: "
                    f"{case.case_id}"
                )

            case_ids.add(
                case.case_id
            )

            cases.append(case)

    return cases

def select_eval_cases(
    cases: list[RetrievalEvalCase],
    split: Literal[
        "dev",
        "holdout",
    ],
) -> list[RetrievalEvalCase]:
    """按 dev / holdout 选择 retrieval cases。"""

    return [
        case
        for case in cases
        if case.split == split
    ]
