"""D04 Task 3：校验研究结果引用的证据是否来自本次提供的资料。"""

import json
from typing import Literal

from stock_agent.schemas.research_output import (
    EvidenceDataMode,
    OutputDataMode,
    RequestDataMode,
    ResearchOutput,
)
from langchain.messages import ToolMessage


class IncompleteResponseError(ValueError):
    """模型响应被截断，不能作为完整结果或继续执行工具。"""


class EvidenceValidationError(ValueError):
    _MESSAGES = {
        "unknown_evidence_id": "未知 evidence_id",
        "evidence_data_mode_conflict": "同一 evidence_id 的 data mode 冲突",
        "evidence_data_mode_invalid": "evidence 的 data mode 无效",
        "evidence_data_mode_missing": "evidence 缺少 data mode",
        "data_mode_not_allowed": "证据 data mode 不符合请求策略",
        "data_mode_mismatch": "数据 mode 不匹配",
    }

    def __init__(
        self,
        code: Literal[
            "unknown_evidence_id",
            "evidence_data_mode_conflict",
            "evidence_data_mode_invalid",
            "evidence_data_mode_missing",
            "data_mode_not_allowed",
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


def collect_evidence_data_modes(messages) -> dict[str, EvidenceDataMode]:
    evidence_modes = {}

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        if message.name not in {"get_quote", "get_company_profile", "retrieve_knowledge"}:
            continue
        if message.status != "success":
            continue

        content = message.content
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                continue

        items = content if isinstance(content, list) else [content]
        for item in items:
            if not isinstance(item, dict):
                continue
            evidence_id = item.get("evidence_id")
            data_mode = item.get("data_mode")
            if not evidence_id:
                continue
            if data_mode not in {"fixture", "historical", "live"}:
                raise EvidenceValidationError(
                    "evidence_data_mode_invalid",
                    context={"evidence_id": evidence_id, "data_mode": data_mode},
                )
            existing = evidence_modes.get(evidence_id)
            if existing is not None and existing != data_mode:
                raise EvidenceValidationError(
                    "evidence_data_mode_conflict",
                    context={
                        "evidence_id": evidence_id,
                        "first_mode": existing,
                        "second_mode": data_mode,
                    },
                )
            evidence_modes[evidence_id] = data_mode

    return evidence_modes


def resolve_output_data_mode(
    output: ResearchOutput,
    evidence_modes: dict[str, EvidenceDataMode],
) -> OutputDataMode | None:
    cited_ids = {
        evidence_id
        for claim in output.facts + output.inferences
        for evidence_id in claim.evidence_ids
    }
    cited_modes = {
        evidence_modes[evidence_id]
        for evidence_id in cited_ids
        if evidence_id in evidence_modes
    }

    if len(cited_modes) > 1:
        return "mixed"
    if cited_modes:
        return next(iter(cited_modes))
    return None


def validate_evidence(
    output: ResearchOutput,
    allowed_ids: set[str],
    evidence_modes: dict[str, EvidenceDataMode],
    request_mode: RequestDataMode,
) -> ResearchOutput:
    """检查引用 ID、请求模式和最终资料模式；output 须先通过 Pydantic 校验。"""
    cited_ids = set()
    for claim in output.facts + output.inferences:
        cited_ids.update(claim.evidence_ids)
        if not set(claim.evidence_ids) <= allowed_ids:
            invalid_ids = set(claim.evidence_ids) - allowed_ids
            raise EvidenceValidationError("unknown_evidence_id", context={
                    "invalid_evidence_ids": invalid_ids,
                    "allowed_ids": sorted(allowed_ids),
                    "claim": claim.text,
                },)

    missing_modes = cited_ids - evidence_modes.keys()
    if missing_modes:
        raise EvidenceValidationError(
            "evidence_data_mode_missing",
            context={"evidence_ids": sorted(missing_modes)},
        )

    available_modes = set(evidence_modes.values())
    if request_mode != "mixed" and available_modes - {request_mode}:
        raise EvidenceValidationError(
            "data_mode_not_allowed",
            context={
                "request_mode": request_mode,
                "evidence_modes": sorted(available_modes),
            },
        )

    expected_data_mode = resolve_output_data_mode(output, evidence_modes)
    if output.data_mode != expected_data_mode:
        raise EvidenceValidationError("data_mode_mismatch")

    return output

def parse_final_output(state) -> ResearchOutput:
    """解析最后一条模型消息；Pydantic 校验错误原样向外传播。"""
    message = state["messages"][-1]
    return ResearchOutput.model_validate_json(message.content)
