import asyncio
from typing import cast

from langchain_core.language_models import BaseChatModel
import pytest

from stock_agent.company import resolver
from stock_agent.company.registry import SecurityRecord
from stock_agent.company.resolver import (
    SemanticTargetAnalysis,
    SemanticTargetInterpretation,
)


SECURITIES = {
    symbol: SecurityRecord(
        symbol=symbol,
        name=symbol,
        cik=str(index).zfill(10),
    )
    for index, symbol in enumerate(
        ("NVDA", "AAPL", "GOOG", "GOOGL", "AI"),
        start=1,
    )
}


class UnexpectedModel:
    def with_structured_output(self, schema):
        raise AssertionError("semantic model must not be called")


class SemanticModel:
    def __init__(self, analysis: SemanticTargetAnalysis):
        self.analysis = analysis
        self.calls = 0

    def with_structured_output(self, schema):
        assert schema is SemanticTargetAnalysis
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return self.analysis


def install_registry(monkeypatch):
    calls: list[str] = []

    def lookup_security(symbol, *, fallback_provider_factory):
        normalized = symbol.strip().upper()
        calls.append(normalized)
        return SECURITIES.get(normalized)

    monkeypatch.setattr(
        resolver,
        "lookup_security",
        lookup_security,
    )
    return calls


def resolve(message: str, model) -> resolver.TargetResolution:
    return asyncio.run(
        resolver.resolve_targets(
            message,
            model=cast(BaseChatModel, model),
            fallback_provider_factory=None,
        )
    )


@pytest.mark.parametrize(
    "message",
    [
        "NVDA 现在多少钱",
        "nvidia 最近怎么看",
        "达子最近怎么看",
    ],
)
def test_deterministic_company_mentions_resolve_without_model(
    monkeypatch,
    message: str,
) -> None:
    install_registry(monkeypatch)

    result = resolve(message, UnexpectedModel())

    assert result.status == "resolved"
    assert result.resolved_targets == ["NVDA"]


def test_alias_resolves_without_calling_model(monkeypatch) -> None:
    install_registry(monkeypatch)

    result = resolve("英伟达接下来的走势", UnexpectedModel())

    assert result.status == "resolved"
    assert result.resolved_targets == ["NVDA"]


def test_alias_mention_preserves_original_message_text() -> None:
    mentions = resolver.find_alias_mentions("NVIDIA 怎么看")

    assert mentions[0].text == "NVIDIA"


def test_explicit_ticker_and_alias_preserve_multiple_targets(
    monkeypatch,
) -> None:
    install_registry(monkeypatch)

    result = resolve("比较 NVDA 和苹果", UnexpectedModel())

    assert result.status == "resolved"
    assert result.resolved_targets == ["NVDA", "AAPL"]


def test_macro_token_is_rejected_without_losing_verified_ticker(
    monkeypatch,
) -> None:
    calls = install_registry(monkeypatch)
    model = SemanticModel(
        SemanticTargetAnalysis(
            interpretations=[
                SemanticTargetInterpretation(
                    mention="CPI",
                    is_security_target=False,
                )
            ]
        )
    )

    result = resolve("最近 CPI 后 NVDA 怎么走", model)

    assert result.status == "resolved"
    assert result.resolved_targets == ["NVDA"]
    assert calls == ["CPI", "NVDA"]
    assert model.calls == 1


def test_alias_with_two_share_classes_remains_ambiguous(
    monkeypatch,
) -> None:
    install_registry(monkeypatch)
    model = SemanticModel(
        SemanticTargetAnalysis(
            interpretations=[
                SemanticTargetInterpretation(
                    mention="Google",
                    is_security_target=True,
                    candidates=["GOOG", "GOOGL"],
                )
            ]
        )
    )

    result = resolve("Google 怎么看", model)

    assert result.status == "ambiguous"
    assert result.resolved_targets == []
    assert result.ambiguous_targets[0].candidates == ["GOOG", "GOOGL"]


def test_long_tail_candidate_is_verified_by_registry(monkeypatch) -> None:
    calls = install_registry(monkeypatch)
    model = SemanticModel(
        SemanticTargetAnalysis(
            interpretations=[
                SemanticTargetInterpretation(
                    mention="老黄那家公司",
                    is_security_target=True,
                    candidates=["NVDA"],
                )
            ]
        )
    )

    result = resolve("老黄那家公司怎么看", model)

    assert result.status == "resolved"
    assert result.resolved_targets == ["NVDA"]
    assert calls == ["NVDA"]


def test_invalid_llm_candidate_does_not_enter_resolved_targets(
    monkeypatch,
) -> None:
    install_registry(monkeypatch)
    model = SemanticModel(
        SemanticTargetAnalysis(
            interpretations=[
                SemanticTargetInterpretation(
                    mention="那个芯片公司",
                    is_security_target=True,
                    candidates=["FAKE"],
                )
            ]
        )
    )

    result = resolve("帮我看看那个芯片公司", model)

    assert result.status == "unresolved"
    assert result.resolved_targets == []
    assert result.unresolved_mentions == ["那个芯片公司"]


def test_semantic_analysis_removes_bare_ai_but_preserves_nvda(
    monkeypatch,
) -> None:
    install_registry(monkeypatch)
    model = SemanticModel(
        SemanticTargetAnalysis(
            interpretations=[
                SemanticTargetInterpretation(
                    mention="AI",
                    is_security_target=False,
                )
            ]
        )
    )

    result = resolve("AI 对 NVDA 有什么影响", model)

    assert result.status == "resolved"
    assert result.resolved_targets == ["NVDA"]


def test_no_security_target_is_absent(
    monkeypatch,
) -> None:
    install_registry(monkeypatch)
    model = SemanticModel(SemanticTargetAnalysis())

    result = resolve("今天市场怎么样", model)

    assert result.status == "absent"
    assert result.resolved_targets == []


def test_unresolved_second_target_does_not_hide_accepted_target(
    monkeypatch,
) -> None:
    install_registry(monkeypatch)
    model = SemanticModel(
        SemanticTargetAnalysis(
            interpretations=[
                SemanticTargetInterpretation(
                    mention="一家我最近提到的芯片公司",
                    is_security_target=True,
                )
            ]
        )
    )

    result = resolve(
        "比较 NVDA 和一家我最近提到的芯片公司",
        model,
    )

    assert result.status == "unresolved"
    assert result.resolved_targets == ["NVDA"]
    assert result.unresolved_mentions == [
        "一家我最近提到的芯片公司",
    ]
