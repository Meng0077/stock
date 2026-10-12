from dataclasses import dataclass
from typing import Literal

from langchain_core.language_models import (
    BaseChatModel,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)
import re

from stock_agent.company.aliases import (
    SECURITY_ALIASES,
)

from collections.abc import Callable

from stock_agent.company.registry import (
    SecurityRecord,
    lookup_security,
)


import json

from typing import Self

from pydantic import (
    StrictBool,
    model_validator,
)

SEMANTIC_TARGET_PROMPT = """
你是股票研究系统中的 Security Target Resolver。

你的唯一职责是：

识别用户问题中哪些自然语言表达
是在指美股证券，并给出可能的 ticker。

你不负责：
- 回答股票问题；
- 做技术分析；
- 判断涨跌；
- 分析宏观数据；
- 验证 ticker 是否真实存在。

Ticker 是否真实存在，
后续会由 Security Registry 验证。

系统已经先执行了确定性解析。
输入中会提供：
- deterministic_mentions；
- verified_resolved_targets；
- ambiguous_targets；
- rejected_mentions；
- focus_mentions。

规则：

1. verified_resolved_targets 是 Registry
   已确认存在的证券。
   不要无故修改这些可靠结果。

2. focus_mentions 是当前必须进行语义判断的表达。

3. 如果 focus mention 在当前上下文中
   不是证券，例如：
   CPI、PPI、AI 概念，
   输出：
   is_security_target=false
   candidates=[]

4. 如果用户确实在指证券，
   输出：
   is_security_target=true

5. 如果能可靠判断 ticker，
   candidates 填 ticker。

6. 如果能确定是在指证券，
   但无法可靠确定具体 ticker，
   candidates=[]。

7. 如果输入中的 ambiguous target
   已经给出了候选集合，
   只能根据上下文在这些候选中消歧，
   不得创造无关 ticker。

8. 还要检查整句话中是否存在
   deterministic resolver 完全漏掉的证券指代。

   例如：
   “比较 NVDA 和老黄那个公司”

   deterministic resolver 可能只识别 NVDA，
   你还需要识别
   “老黄那个公司”。

9. mention 必须使用用户原文中的文本，
   不要自己创造新的 mention。

10. 不要因为认识某个公司，
    就跳过 Registry。
    你输出的 ticker 只是 candidate。

例子：

“CPI 后 NVDA 怎么走”

CPI:
is_security_target=false

NVDA 已经是可靠 target，
不需要重复输出。

“老黄那个公司怎么看”

老黄那个公司:
is_security_target=true
candidates=["NVDA"]

“AI 对 NVDA 有什么影响”

AI:
is_security_target=false

“Google Class A 怎么看”

Google:
is_security_target=true
candidates=["GOOGL"]
"""


TargetResolutionStatus = Literal[
    "resolved",
    "ambiguous",
    "unresolved",
    "absent",
]

class AmbiguousTarget(BaseModel):
    """
    一个已经识别到具体 mention，
    但无法唯一确定证券代码的 target。

    例如：
        "Google"
        -> GOOG / GOOGL
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    mention: str
    candidates: list[str] = Field(min_length=2)

class TargetResolution(BaseModel):
    """
    一次用户输入的证券标的解析结果。

    resolved_targets:
        已经能够唯一确定的证券 ticker。

    ambiguous_targets:
        已经识别到证券实体，
        但存在多个合理 ticker 候选。

    unresolved_mentions:
        能判断用户在指代某个证券，
        但目前无法可靠确定具体 ticker。

    status 不单独存储，
    而是根据以上事实自动推导，
    避免状态和实际解析结果发生冲突。
    """
    resolved_targets: list[str] = Field(default_factory=list)

    ambiguous_targets: list[AmbiguousTarget] = Field(default_factory=list)

    unresolved_mentions: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def status(
        self,
    ) -> TargetResolutionStatus:
        """
        根据当前仍未解决的问题，
        推导整个 Target Resolution 的状态。
        """
        if self.ambiguous_targets:
            return "ambiguous"

        elif self.unresolved_mentions:
            return "unresolved"

        elif self.resolved_targets:
            return "resolved"

        else:
            return "absent"

TargetMentionSource = Literal[
    "explicit",
    "alias",
]

@dataclass(frozen=True)
class TargetMention:
    """
    用户原始问题中识别到的一处证券标的表达。

    text:
        原文中的实际文本。

    start / end:
        在原始 message 中的字符区间，
        使用 Python slice 的 [start, end) 语义。

    source:
        这处 mention 是由哪一种确定性规则发现的。

    candidates:
        该 mention 可能对应的 ticker。
        单一证券通常只有一个；
        Google 这类 share class 歧义可能有多个。
    """

    text: str
    start: int
    end: int
    source: TargetMentionSource
    candidates: tuple[str, ...]

class SemanticTargetInterpretation(BaseModel):
    """
    LLM 对一个自然语言证券指代的语义判断。

    mention:
        必须来自用户原始文本。

    is_security_target:
        当前语境中是否真的在指证券。

    candidates:
        LLM 猜测的 ticker。

        这里只是 candidate，
        后续必须经过 Security Registry 验证。

        如果用户明显在指证券，
        但模型无法可靠确定 ticker，
        candidates 可以为空。
    """
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    mention: str = Field(min_length=1)

    is_security_target: StrictBool

    candidates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_interpretation(self) -> Self:
        if not self.is_security_target and self.candidates:
            raise ValueError(
                "non-security mention must not contain ticker candidates"
            )

        return self

class SemanticTargetAnalysis(BaseModel):
    """
    LLM 对确定性 Resolver 未能完全解决部分的分析结果。
    """
    model_config = ConfigDict(
        extra="forbid",
    )

    interpretations: list[SemanticTargetInterpretation] = Field(default_factory=list)

"""
message
   ↓
找 explicit ticker
   ↓
找 known alias
   ↓
合并已知 target
   ↓
判断 coverage
   ↓
必要时 LLM
   ↓
验证 candidate
   ↓
TargetResolution
"""

# Explicit ticker scanner 只负责发现用户直接写出的 ticker-like token。
#
# 裸 ticker 使用大写作为强信号，避免把普通英文短词大量误识别为 ticker。
# "$" 前缀本身已经明确表达证券代码，因此允许 "$nvda" 这种小写写法。
#
# 当前 v1 支持：
# NVDA
# $NVDA / $nvda
# BRK.B
# BRK-B
#
# 是否为真实证券不在这里判断，
# 后续统一交给 Security Registry。
_EXPLICIT_TICKER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?:"
    r"\$([A-Za-z]{1,5}(?:[.-][A-Za-z])?)"
    r"|"
    r"([A-Z]{1,5}(?:[.-][A-Z])?)"
    r")"
    r"(?![A-Za-z0-9_])"
)

def find_explicit_ticker_mentions(
    message: str,
) -> list[TargetMention]:
    """
    找出用户直接写出的 ticker-like mention。

    这里只做词法识别，
    不判断 candidate 是否为真实证券。
    """

    mentions: list[TargetMention] = []

    for match in _EXPLICIT_TICKER_PATTERN.finditer(
        message
    ):
        raw_ticker = match.group(1) or match.group(2)

        ticker = raw_ticker.upper()

        start, end = match.span()

        mentions.append(
            TargetMention(
                text=message[start:end],
                start=start,
                end=end,
                source="explicit",
                candidates=(ticker,),
            )
        )

    return mentions

def find_explicit_ticker_candidates(
    message: str,
) -> list[str]:
    """
    返回显式 ticker mention 中去重后的 candidate ticker。

    具体字符位置由 find_explicit_ticker_mentions()
    负责保留。
    """

    candidates: list[str] = []

    for mention in find_explicit_ticker_mentions(message):
        ticker = mention.candidates[0]
        if ticker not in candidates:
            candidates.append(ticker)

    return candidates

def _build_alias_pattern(
    alias: str,
) -> re.Pattern[str]:
    """
    为一条 alias 构造匹配规则。

    包含英文字母的 alias 使用单词边界约束，
    防止 apple 匹配 pineapple。

    中文 alias 直接按字面匹配。
    """

    escaped_alias = re.escape(alias)

    has_ascii_letter = any(
        char.isascii()
        and char.isalpha()
        for char in alias
    )

    if has_ascii_letter:
        return re.compile(
            r"(?<![A-Za-z0-9])"
            + escaped_alias
            + r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        )

    return re.compile(
        escaped_alias,
        re.IGNORECASE,
    )

def find_alias_mentions(
    message: str,
) -> list[TargetMention]:
    """
    找出所有 deterministic alias mention。

    当前只负责发现，
    alias 之间的重叠由 merge_target_mentions()
    统一处理。
    """
    mentions: list[TargetMention] = []

    for alias, candidates in SECURITY_ALIASES.items():
        pattern = _build_alias_pattern(alias)
        for match in pattern.finditer(message):
            start, end = match.span()
            mentions.append(TargetMention(
                text=message[start:end],
                start=start,
                end=end,
                source="alias",
                candidates=tuple(candidates),
            ))
    mentions.sort(key=lambda mention: mention.start)
    return mentions

def find_alias_matches(
    message: str,
) -> list[
    tuple[
        str,
        tuple[str, ...],
    ]
]:
    """
    返回 alias scanner 的简化结果。

    完整位置数据由 find_alias_mentions()
    保留。
    """
    matches: list[
        tuple[
            str,
            tuple[str, ...],
        ]
    ] = []

    alias_mentions = find_alias_mentions(message)
    return [
        (mention.text, mention.candidates)
        for mention in alias_mentions
    ]

def _mentions_overlap(
    left: TargetMention,
    right: TargetMention,
) -> bool:
    return (
        left.start < right.end
        and right.start < left.end
    )

_SOURCE_PRIORITY = {
    "explicit": 0,
    "alias": 1,
}

def merge_target_mentions(
    *mention_groups: list[TargetMention],
) -> list[TargetMention]:
    """
    合并不同 deterministic scanner 产生的 mentions。

    对重叠 mention：
    - 优先保留覆盖范围更长的表达；
    - 长度相同时，explicit 优先于 alias。

    不合并原文中不同位置的 mention。
    即使它们最终指向同一个 ticker，
    也要保留，以供后续 coverage check 使用。
    """
    mentions = [
        mention
        for group in mention_groups
        for mention in group
    ]

    ranked_mentions = sorted(
        mentions,
        key=lambda mention: (
            mention.start - mention.end,
            _SOURCE_PRIORITY[mention.source],
            mention.start
        )
    )

    selected = []
    for mention in ranked_mentions:
        overlaps_existing = any(
            _mentions_overlap(mention, existing)
            for existing in selected
        )
        if not overlaps_existing:
            selected.append(mention)

    selected.sort(key=lambda mention: mention.start)
    return selected

def collect_candidate_tickers(
    mentions: list[TargetMention],
) -> list[str]:
    """
    从 mentions 中收集需要后续 Registry 验证的 ticker。

    保持首次出现顺序，
    同一个 ticker 只验证一次。
    """
    tickers: list[str] = []
    for mention in mentions:
        for ticker in mention.candidates:
            if ticker not in tickers:
                tickers.append(ticker)
    return tickers

def verify_target_candidates(
    mentions: list[TargetMention],
    *,
    fallback_provider_factory: (
        Callable[[], object] | None
    ),
) -> dict[str, str]:
    """
    验证所有 mention 中出现的 ticker candidate。

    返回：
        candidate ticker
        -> Registry 确认后的 canonical symbol

    例如：
        {
            "NVDA": "NVDA",
            "AAPL": "AAPL",
        }

    Registry 查不到的 candidate 不进入结果。
    """
    result = {}
    for candidate in collect_candidate_tickers(mentions):
        security = lookup_security(
            symbol=candidate,
            fallback_provider_factory=fallback_provider_factory,
        )
        if security is not None:
            result[candidate] = security.symbol

    return result

def classify_target_mentions(
    mentions: list[TargetMention],
    verified_candidates: dict[str, str],
) -> tuple[
    list[str],
    list[AmbiguousTarget],
    list[TargetMention],
]:
    """
    根据 Registry 验证结果，
    将 mention 分成：

    - resolved target；
    - ambiguous target；
    - rejected mention。
    """
    resolved_targets: list[str] = []

    ambiguous_targets: list[
        AmbiguousTarget
    ] = []

    rejected_mentions: list[
        TargetMention
    ] = []

    for mention in mentions:
        verified_symbols: list[str] = []

        for candidate in mention.candidates:
            symbol = verified_candidates.get(candidate)
            if symbol is not None and symbol not in verified_symbols:
                verified_symbols.append(symbol)
        if not verified_symbols:
            rejected_mentions.append(mention)
            continue
        if len(verified_symbols) > 1:
            ambiguous_targets.append(
                AmbiguousTarget(
                    mention=mention.text,
                    candidates=verified_symbols,
                )
            )
            continue

        symbol = verified_symbols[0]
        if symbol not in resolved_targets:
            resolved_targets.append(symbol)

    return resolved_targets, ambiguous_targets, rejected_mentions


_MULTI_TARGET_PATTERN = re.compile(
    r"(?:"
    r"比较|对比|相比|"
    r"和|与|跟|以及|还有|还是|"
    r"哪个|哪只|哪一个"
    r")"
    r"|"
    r"(?<![A-Za-z0-9])"
    r"(?:vs|versus)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# 这些 ticker 本身可能是真实证券，
# 但裸写时同时具有很强的普通语言含义。
#
# "$AI" 这种显式 cashtag 不属于语义歧义，
# 因为用户已经明确表达证券代码语境。
_SEMANTICALLY_AMBIGUOUS_BARE_TICKERS = {
    "AI",
}

def has_multi_target_signal(
    message: str,
) -> bool:
    """
    判断用户文本是否明显表达了
    多证券比较或并列关系。

    这里只作为 Coverage Check 的触发信号，
    不负责实际提取 target。
    """
    return _MULTI_TARGET_PATTERN.search(message) is not None

def _is_semantically_ambiguous_explicit_mention(
    mention: TargetMention,
) -> bool:
    """
    判断一处 explicit mention
    是否存在明显的普通语言语义歧义。
    """
    if mention.source != "explicit":
        return False

    if mention.text.startswith("$"):
        return False

    return any(candidate in _SEMANTICALLY_AMBIGUOUS_BARE_TICKERS for candidate in mention.candidates)

def has_semantically_ambiguous_explicit_ticker(
    mentions: list[TargetMention],
) -> bool:
    """
    检查是否存在需要结合上下文理解的裸 ticker。

    "$AI" 具有明确证券语境，
    因此不进入这一规则。
    """
    return any(_is_semantically_ambiguous_explicit_mention(mention) for mention in mentions)

def needs_semantic_resolution(
    message: str,
    *,
    mentions: list[TargetMention],
    resolved_targets: list[str],
    ambiguous_targets: list[
        AmbiguousTarget
    ],
    rejected_mentions: list[
        TargetMention
    ],
) -> bool:
    """
    判断确定性解析结果是否已经足够覆盖用户问题。
    """
    # 完全没有 deterministic mention 时，
    # 无法区分“确实没有证券 target”
    # 和“存在长尾自然语言 target”。
    if not mentions:
        return True

    # Registry 拒绝的 token 可能只是普通术语，也可能是用户试图表达但系统无法验证的证券。
    if rejected_mentions:
        return True

    # deterministic alias 自身存在多候选时
    if ambiguous_targets:
        return True

    # Registry 无法判断用户当前使用的是哪种语义。
    if has_semantically_ambiguous_explicit_ticker(mentions):
        return True

    # 用户明显在表达多个 target，
    if has_multi_target_signal(message) and len(resolved_targets) < 2:
        return True

    return False

def build_semantic_target_input(
    message: str,
    *,
    mentions: list[TargetMention],
    resolved_targets: list[str],
    ambiguous_targets: list[
        AmbiguousTarget
    ],
    rejected_mentions: list[
        TargetMention
    ]
) -> dict[str, object]:
    """
    把 deterministic resolution
    转成 Semantic Resolver 所需的最小上下文。

    LLM 应重点处理尚未解决或存在语义风险的部分，
    而不是重新做一遍整个 Resolver。
    """
    focus_mentions: list[str] = []

    for mention in rejected_mentions:
        if mention.text not in focus_mentions:
            focus_mentions.append(mention.text)

    for target in ambiguous_targets:
        if target.mention not in focus_mentions:
            focus_mentions.append(target.mention)

    for mention in mentions:
        if mention.text not in focus_mentions and _is_semantically_ambiguous_explicit_mention(mention):
            focus_mentions.append(mention.text)

    return {
        "message": message,
        "deterministic_mentions": [
            {
                "text": mention.text,
                "source": mention.source,
                "candidates": list(
                    mention.candidates
                ),
            }
            for mention in mentions
        ],
        "verified_resolved_targets": list(resolved_targets),
        "ambiguous_targets": [
            target.model_dump()
            for target in ambiguous_targets
        ],
        "rejected_mentions": [
            mention.text
            for mention in rejected_mentions
        ],
        "focus_mentions": focus_mentions,
    }

async def analyze_semantic_targets(
    message: str,
    *,
    mentions: list[TargetMention],
    resolved_targets: list[str],
    ambiguous_targets: list[
        AmbiguousTarget
    ],
    rejected_mentions: list[
        TargetMention
    ],
    model: BaseChatModel,
) -> SemanticTargetAnalysis:
    """
    让 LLM 只处理 deterministic resolver
    无法可靠解决的语义部分。

    输出仍然只是 semantic guess，
    ticker candidate 后续必须经过 Registry。
    """
    structured_model = model.with_structured_output(SemanticTargetAnalysis)
    input = build_semantic_target_input(
        message,
        mentions=mentions,
        resolved_targets=resolved_targets,
        ambiguous_targets=ambiguous_targets,
        rejected_mentions=rejected_mentions,
    )

    result = await structured_model.ainvoke([{
        "role": "system",
        "content": SEMANTIC_TARGET_PROMPT
    }, {
        "role": "user",
        "content": json.dumps(input, ensure_ascii=False,)
    }])

    if isinstance(result, SemanticTargetAnalysis):
        return result

    return SemanticTargetAnalysis.model_validate(result)

def remove_unstable_resolved_target(
    mention: TargetMention,
    *,
    mentions: list[TargetMention],
    verified_candidates: dict[str, str],
    resolved_targets: list[str],
) -> None:
    """
    撤销仅由一个语义高风险 mention
    支持的 resolved target。

    如果还有其他稳定 mention
    指向同一个 ticker，则保留。
    """

    for candidate in mention.candidates:
        symbol = verified_candidates.get(
            candidate
        )

        if symbol is None:
            continue

        has_stable_support = any(
            other is not mention
            and not (
                _is_semantically_ambiguous_explicit_mention(
                    other
                )
            )
            and any(
                verified_candidates.get(
                    other_candidate
                )
                == symbol
                for other_candidate
                in other.candidates
            )
            for other in mentions
        )

        if (
            not has_stable_support
            and symbol in resolved_targets
        ):
            resolved_targets.remove(
                symbol
            )

def apply_semantic_target_analysis(
    message: str,
    *,
    mentions: list[TargetMention],
    verified_candidates: dict[str, str],
    resolved_targets: list[str],
    ambiguous_targets: list[
        AmbiguousTarget
    ],
    rejected_mentions: list[
        TargetMention
    ],
    analysis: SemanticTargetAnalysis,
    fallback_provider_factory: (
        Callable[[], object] | None
    ),
) -> TargetResolution:
    """
    将 LLM semantic interpretation
    合并进确定性解析结果。

    流程：
    1. deterministic scanner 找出证券表达；
    2. Registry 验证 candidate ticker；
    3. 分类 resolved / ambiguous / rejected；
    4. Coverage 足够时直接返回；
    5. Coverage 不足时才让 LLM 补语义；
    6. LLM candidate 再经 Registry 后生成最终结果。
    """

    resolved = list(
        resolved_targets
    )

    ambiguous_by_mention = {
        target.mention.casefold(): target
        for target in ambiguous_targets
    }

    unresolved: list[str] = []

    processed_mentions: set[str] = set()

    normalized_message = (
        message.casefold()
    )

    for interpretation in (
        analysis.interpretations
    ):
        mention_text = (
            interpretation.mention.strip()
        )

        mention_key = (
            mention_text.casefold()
        )

        if (
            mention_key
            not in normalized_message
        ):
            continue

        processed_mentions.add(
            mention_key
        )

        matching_mentions = [
            mention
            for mention in mentions
            if (
                mention.text.casefold()
                == mention_key
            )
        ]

        original_ambiguity = (
            ambiguous_by_mention.pop(
                mention_key,
                None,
            )
        )

        semantic_risk_mentions = [
            mention
            for mention
            in matching_mentions
            if (
                _is_semantically_ambiguous_explicit_mention(
                    mention
                )
            )
        ]

        for mention in semantic_risk_mentions:
            remove_unstable_resolved_target(
                mention,
                mentions=mentions,
                verified_candidates=(
                    verified_candidates
                ),
                resolved_targets=resolved,
            )

        # deterministic 已经确认该 mention 是证券，
        # LLM 只能帮助缩小候选范围，不能否定这个事实。
        if not interpretation.is_security_target:
            if original_ambiguity is not None:
                ambiguous_by_mention[mention_key] = original_ambiguity
            continue

        candidates = [
            candidate.strip().upper()
            for candidate
            in interpretation.candidates
            if candidate.strip()
        ]

        if original_ambiguity is not None:
            allowed = {
                candidate.upper()
                for candidate
                in original_ambiguity.candidates
            }

            candidates = [
                candidate
                for candidate in candidates
                if candidate in allowed
            ]

            if not candidates:
                ambiguous_by_mention[
                    mention_key
                ] = original_ambiguity

                continue

        elif semantic_risk_mentions:
            allowed = {
                candidate.upper()
                for mention
                in semantic_risk_mentions
                for candidate
                in mention.candidates
            }

            candidates = [
                candidate
                for candidate in candidates
                if candidate in allowed
            ]

        if not candidates:
            if (
                mention_text
                not in unresolved
            ):
                unresolved.append(
                    mention_text
                )

            continue

        verified_symbols: list[str] = []

        for candidate in candidates:
            symbol = verified_candidates.get(
                candidate
            )

            if symbol is None:
                security = lookup_security(
                    candidate,
                    fallback_provider_factory=(
                        fallback_provider_factory
                    ),
                )

                if security is None:
                    continue

                symbol = security.symbol

                verified_candidates[
                    candidate
                ] = symbol

            if (
                symbol
                not in verified_symbols
            ):
                verified_symbols.append(
                    symbol
                )

        if not verified_symbols:
            if (
                mention_text
                not in unresolved
            ):
                unresolved.append(
                    mention_text
                )

            continue

        if len(verified_symbols) == 1:
            symbol = verified_symbols[0]

            if symbol not in resolved:
                resolved.append(
                    symbol
                )

            continue

        ambiguous_by_mention[
            mention_key
        ] = AmbiguousTarget(
            mention=mention_text,
            candidates=verified_symbols,
        )

    for mention in rejected_mentions:
        if (
            mention.text.casefold()
            in processed_mentions
        ):
            continue

        if mention.text not in unresolved:
            unresolved.append(
                mention.text
            )

    for mention in mentions:
        if not (
            _is_semantically_ambiguous_explicit_mention(
                mention
            )
        ):
            continue

        if (
            mention.text.casefold()
            in processed_mentions
        ):
            continue

        remove_unstable_resolved_target(
            mention,
            mentions=mentions,
            verified_candidates=(
                verified_candidates
            ),
            resolved_targets=resolved,
        )

        if mention.text not in unresolved:
            unresolved.append(
                mention.text
            )

    return TargetResolution(
        resolved_targets=resolved,
        ambiguous_targets=list(
            ambiguous_by_mention.values()
        ),
        unresolved_mentions=unresolved,
    )

async def resolve_targets(
    message: str,
    *,
    model: BaseChatModel,
    fallback_provider_factory: (
        Callable[[], object] | None
    ),
) -> TargetResolution:
    """
    从用户自然语言中解析证券研究标的。

    流程：
    1. 继承 deterministic 结果
    2. 限制 LLM 不能随便改已有候选
    3. 修正 AI/CPI 这类语义问题
    4. LLM 新 ticker 必须再过 Registry
    5. LLM 漏处理时保守地标成 unresolved
    6. 返回最终 TargetResolution。
    """
    mentions = merge_target_mentions(
        find_explicit_ticker_mentions(message),
        find_alias_mentions(message),
    )

    verified_candidates = verify_target_candidates(
        mentions=mentions,
        fallback_provider_factory=fallback_provider_factory,
    )

    resolved_targets, ambiguous_targets, rejected_mentions = classify_target_mentions(
        mentions=mentions,
        verified_candidates=verified_candidates,
    )

    if not needs_semantic_resolution(
        message,
        mentions=mentions,
        resolved_targets=resolved_targets,
        ambiguous_targets=ambiguous_targets,
        rejected_mentions=rejected_mentions,
        ):
        return TargetResolution(
            resolved_targets=resolved_targets,
            ambiguous_targets=ambiguous_targets,
            unresolved_mentions=[],
        )

    analysis = await analyze_semantic_targets(
        message=message,
        mentions=mentions,
        resolved_targets=resolved_targets,
        ambiguous_targets=ambiguous_targets,
        rejected_mentions=rejected_mentions,
        model=model,
    )

    return apply_semantic_target_analysis(
        message=message,
        mentions=mentions,
        resolved_targets=resolved_targets,
        ambiguous_targets=ambiguous_targets,
        rejected_mentions=rejected_mentions,
        analysis=analysis,
        verified_candidates=verified_candidates,
        fallback_provider_factory=fallback_provider_factory,
    )
