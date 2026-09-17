"""D04 Task 3：校验研究结果引用的证据是否来自本次提供的资料。"""

import json
from typing import Literal

from stock_agent.schemas.research_output import ResearchOutput
from langchain.messages import ToolMessage


class IncompleteResponseError(ValueError):
    """模型响应被截断，不能作为完整结果或继续执行工具。"""


class EvidenceValidationError(ValueError):
    _MESSAGES = {
        "unknown_evidence_id": "未知 evidence_id",
        "data_mode_mismatch": "数据 mode 不匹配",
    }

    def __init__(
        self,
        code: Literal[
            "unknown_evidence_id",
            "data_mode_mismatch",
        ],
        *,
        context: dict | None = None,
    ):
        self.code = code
        self.context = context or {}

        message = self._MESSAGES[code]

        if self.context:
            message += f": {self.context}"

        super().__init__(message)


def extract_evidence_ids(value) -> set[str]:
    if isinstance(value, dict):
        evidence_id = value.get("evidence_id")

        return (
            {evidence_id}
            if evidence_id
            else set()
        )

    if isinstance(value, list):
        evidence_ids = set()

        for item in value:
            evidence_ids |= extract_evidence_ids(item)

        return evidence_ids

    return set()


def collect_evidence_ids(messages) -> set[str]:
    evidence_ids = set()

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        if message.name not in {"get_quote", "get_company_profile", "retrieve_knowledge"}:
            continue
        content = message.content

        if message.status != "success":
            continue


        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue

        evidence_ids |= extract_evidence_ids(content)

    return evidence_ids


def validate_evidence(
    output: ResearchOutput,
    allowed_ids: set[str],
    expected_data_mode: Literal["fixture", "historical", "live"],
) -> ResearchOutput:
    """检查资料模式和每个引用 ID；output 须先通过 Pydantic 校验。"""
    if output.data_mode != expected_data_mode:
        raise EvidenceValidationError("data_mode_mismatch")


    for claim in output.facts + output.inferences:
        if not set(claim.evidence_ids) <= allowed_ids:
            invalid_ids = set(claim.evidence_ids) - allowed_ids
            raise EvidenceValidationError("unknown_evidence_id", context={
                    "invalid_evidence_ids": invalid_ids,
                    "allowed_ids": sorted(allowed_ids),
                    "claim": claim.text,
                },)

    return output

def parse_final_output(state) -> ResearchOutput:
    """解析最后一条模型消息；Pydantic 校验错误原样向外传播。"""
    message = state["messages"][-1]
    return ResearchOutput.model_validate_json(message.content)
