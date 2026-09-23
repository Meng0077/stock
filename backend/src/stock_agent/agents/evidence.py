from collections.abc import Iterator
import json
from typing import Any
from sqlalchemy import Engine

from langchain.messages import ToolMessage

from stock_agent.financial.evidence import (
    resolve_financial_evidence,
)
from stock_agent.storage.evidence import (
    resolve_rag_evidence,
)
from stock_agent.agents.structured_output import EvidenceValidationError, resolve_output_data_mode
from stock_agent.schemas.research_output import EvidenceDataMode, RequestDataMode, ResearchOutput

EVIDENCE_TOOL_NAMES = {
    "get_quote",
    "get_company_profile",
    "retrieve_knowledge",
    "get_financial_facts",
}

PERSISTED_EVIDENCE_PREFIXES = (
    "rag:",
    "financial:",
)


def iter_evidence_records(
    value: Any,
    inherited_mode: EvidenceDataMode | None = None,
) -> Iterator[tuple[str, EvidenceDataMode | None]]:
    """递归遍历 Tool 返回值中的 evidence。

    Args:
        value:
            ToolMessage 反序列化后的内容。

        inherited_mode:
            上层对象提供的 data_mode。

            例如 Financial Tool：

            {
                "data_mode": "historical",
                "facts": [
                    {"evidence_id": "financial:xxx"}
                ]
            }

            facts 中的 evidence 会继承 historical。

    Yields:
        (evidence_id, data_mode)

    这个函数只负责从任意嵌套 Tool 输出中提取 evidence，
    不负责验证 data_mode 是否有效。
    """

    if isinstance(value, list):
        for item in value:
            yield from iter_evidence_records(
                item,
                inherited_mode=inherited_mode,
            )
        return

    if not isinstance(value, dict):
        return

    # 当前节点如果声明了 data_mode，
    # 子节点默认继承这个 mode。
    current_mode = value.get(
        "data_mode",
        inherited_mode,
    )

    evidence_id = value.get("evidence_id")

    if evidence_id:
        yield evidence_id, current_mode

    # 继续递归所有子结构。
    for child in value.values():
        if isinstance(child, (dict, list)):
            yield from iter_evidence_records(
                child,
                inherited_mode=current_mode,
            )


def parse_tool_content(
    message: ToolMessage,
):
    """把 ToolMessage.content 尽量转换成 Python 对象。"""

    content = message.content

    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    return content


def collect_evidence_ids(
    messages,
) -> set[str]:
    """收集所有成功数据工具返回的 evidence ID。"""

    evidence_ids: set[str] = set()

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue

        if message.name not in EVIDENCE_TOOL_NAMES:
            continue

        if getattr(message, "status", None) == "error":
            continue

        content = parse_tool_content(message)

        if content is None:
            continue

        for evidence_id, _ in iter_evidence_records(content):
            evidence_ids.add(evidence_id)

    return evidence_ids


def collect_evidence_data_modes(
    messages,
) -> dict[str, EvidenceDataMode]:
    """收集 evidence ID 对应的数据模式。"""

    evidence_modes: dict[str, EvidenceDataMode] = {}

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue

        if message.name not in EVIDENCE_TOOL_NAMES:
            continue

        if getattr(message, "status", None) == "error":
            continue

        content = parse_tool_content(message)

        if content is None:
            continue

        for evidence_id, data_mode in iter_evidence_records(content):
            if data_mode not in {"fixture", "historical", "live"}:
                raise EvidenceValidationError(
                    "evidence_data_mode_invalid",
                    context={
                        "evidence_id": evidence_id,
                        "data_mode": data_mode,
                    },
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


def resolve_evidence(
    engine: Engine,
    evidence_id: str,
) -> Any | None:
    """根据 evidence_id 找回持久化的原始证据。

    Args:
        engine:
            PostgreSQL Engine。

        evidence_id:
            Agent 最终输出引用的 evidence ID。

            当前支持：
                rag:*
                financial:*

    Returns:
        rag evidence:
            返回 RAG evidence 对象。

        financial evidence:
            返回 FinancialFact。

        不支持的 evidence 类型或不存在时：
            返回 None。

    这个函数负责：
        - 根据 evidence ID 前缀分发到对应 resolver。

    这个函数不负责：
        - 判断 claim 文本是否真的被证据支持。
        - 判断 output.data_mode。
        - 处理 fixture quote 等非持久化 evidence。
    """
    if evidence_id.startswith("rag:"):
        return resolve_rag_evidence(
            engine=engine,
            evidence_id=evidence_id,
        )

    if evidence_id.startswith("financial:"):
        return resolve_financial_evidence(
            engine=engine,
            evidence_id=evidence_id,
        )

    return None

def validate_persisted_evidence_access(
    engine: Engine,
    evidence_ids: set[str],
) -> None:
    """验证持久化 evidence 是否仍然能够从数据库解析。

    Args:
        engine:
            PostgreSQL Engine。

        evidence_ids:
            最终 ResearchOutput 实际引用的 evidence IDs。

    Raises:
        EvidenceValidationError:
            evidence 属于持久化类型，但数据库中无法找到时抛出。

    当前检查：
        rag:*
        financial:*

    fixture quote 等 evidence 不在这里检查。
    """

    for evidence_id in evidence_ids:
        if not evidence_id.startswith(
            PERSISTED_EVIDENCE_PREFIXES
        ):
            continue

        resolved = resolve_evidence(
            engine=engine,
            evidence_id=evidence_id,
        )

        if resolved is None:
            raise EvidenceValidationError(
                "evidence_not_accessible",
                context={
                    "evidence_id": evidence_id,
                },
            )

def validate_evidence(
    output: ResearchOutput,
    allowed_ids: set[str],
    evidence_modes: dict[str, EvidenceDataMode],
    request_mode: RequestDataMode,
    engine: Engine | None = None,
) -> ResearchOutput:
    """验证最终回答中的 evidence 和 data mode。

    检查：
        1. evidence ID 是否由本次工具调用产生。
        2. 持久化 evidence 是否仍可访问。
        3. 每个引用 evidence 是否具有 data_mode。
        4. request mode 是否允许这些 evidence。
        5. output.data_mode 是否与实际引用一致。
    """
    cited_ids: set[str] = set()

    for claim in output.facts + output.inferences:
        claim_id = set(claim.evidence_ids)
        cited_ids.update(claim_id)
        invalid_ids = claim_id - allowed_ids

        if invalid_ids:
            raise EvidenceValidationError("unknown_evidence_id", context={
                    "invalid_evidence_ids": invalid_ids,
                    "allowed_ids": sorted(allowed_ids),
                    "claim": claim.text,
                },)

    # 已经确认这些 ID 确实来自本次工具调用，
    # 再检查持久 evidence 是否仍能回到数据库原始证据。
    if engine is not None:
        validate_persisted_evidence_access(
            engine,
            evidence_ids=cited_ids,
        )

    missing_modes = cited_ids - evidence_modes.keys()
    if missing_modes:
        raise EvidenceValidationError(
            "evidence_data_mode_missing",
            context={"evidence_ids": sorted(missing_modes)},
        )

    # 这里只看最终回答真正引用的 evidence，
    # 不看 Agent 曾经调用过但最终没有引用的工具。
    cited_modes = {
        evidence_modes[evidence_id]
        for evidence_id in cited_ids
    }
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
