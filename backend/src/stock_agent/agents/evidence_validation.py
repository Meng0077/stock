"""D04 Task 3：校验研究结果引用的证据是否来自本次提供的资料。"""

from typing import Literal

from stock_agent.schemas.research_output import ResearchOutput


class EvidenceValidationError(ValueError):
    """业务错误unknown_evidence_id data_mode_mismatch"""

    _MESSAGES = {
        "unknown_evidence_id": "未知evidence_id",
        "data_mode_mismatch": "数据mode不匹配",
    }

    def __init__(self, code: Literal["unknown_evidence_id", "data_mode_mismatch"]):
        self.code = code
        super().__init__(self._MESSAGES[code])


def validate_evidence(
    output: ResearchOutput,
    allowed_ids: set[str],
    expected_data_mode: Literal["fixture", "historical", "live"],
) -> ResearchOutput:
    """检查资料模式和每个引用 ID；output 须先通过 Pydantic 校验。"""
    if output.data_mode != expected_data_mode:
        raise EvidenceValidationError("data_mode_mismatch")

    for claim in (*output.facts, *output.inferences):
        for evidence_id in claim.evidence_ids:
            if evidence_id not in allowed_ids:
                raise EvidenceValidationError("unknown_evidence_id")

    # allowed_ids 为空且没有声明时，循环不会执行；schema 已要求说明缺失信息。
    return output
