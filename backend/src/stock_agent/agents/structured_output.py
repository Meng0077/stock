"""D04 Task 3：校验研究结果引用的证据是否来自本次提供的资料。"""

from typing import Literal

from stock_agent.schemas.research_output import (
    EvidenceDataMode,
    OutputDataMode,
    ResearchOutput,
)


class IncompleteResponseError(ValueError):
    """模型响应被截断，不能作为完整结果或继续执行工具。"""


class EvidenceValidationError(ValueError):
    _MESSAGES = {
        "unknown_evidence_id": "未知 evidence_id",
        "evidence_data_mode_conflict": "同一 evidence_id 的 data mode 冲突",
        "evidence_data_mode_invalid": "evidence 的 data mode 无效",
        "evidence_data_mode_missing": "evidence 缺少 data mode",
        "evidence_not_accessible": "evidence 无法从持久化存储读取",
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
            "evidence_not_accessible",
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

def parse_final_output(state) -> ResearchOutput:
    """解析最后一条模型消息；Pydantic 校验错误原样向外传播。"""
    message = state["messages"][-1]
    return ResearchOutput.model_validate_json(message.content)
