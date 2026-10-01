from decimal import Decimal
from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from stock_agent.macro.models.snapshot import MacroSnapshot
from stock_agent.market.schemas import Quote
from stock_agent.market.technical import MarketTechnicalSnapshot
from stock_agent.market_reaction.models import MarketReactionResult
from stock_agent.quality.report import DataQualityReport


MARKET_CONTEXT_VERSION: Literal[
    "market-context-v1"
] = "market-context-v1"


# ============================================================
# MarketContext
# ============================================================

ContextComponent = Literal[
    "quote",
    "technical",
    "macro",
    "market_reaction",
]

ContextComponentStatus = Literal[
    "available",
    "missing",
    "not_requested",
]

ComponentQualityStatus = Literal[
    "usable",
    "degraded",
    "rejected",
    "not_assessed",
    "not_requested",
]

COMPONENT_QUALITY_PURPOSE = {
    "quote": "current_price",
    "technical": "daily_technical",
    "macro": "macro_research",
    "market_reaction": "market_reaction",
}

# 质量结果需要按 symbol 隔离
SYMBOL_SCOPED_COMPONENTS: frozenset[
    ContextComponent
] = frozenset({
    "quote",
    "technical",
    "market_reaction",
})

COMPONENT_ORDER: tuple[ContextComponent, ...] = (
    "quote",
    "technical",
    "macro",
    "market_reaction",
)

class ComponentProvenance(BaseModel):
    """一个研究组件已经保留下来的来源和算法版本。"""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    sources: tuple[str, ...] = ()

    versions: tuple[str, ...] = ()

class MarketContextProvenance(BaseModel):
    """MarketContext 的只读来源/版本汇总。"""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
    )

    as_of: AwareDatetime

    context_version: str

    components: dict[
        ContextComponent,
        ComponentProvenance,
    ]

    quality_rule_versions: tuple[str, ...] = ()

class MarketContext(BaseModel):
    """一次市场研究使用的统一结构化上下文。

    MarketContext 不负责：
        - 请求行情；
        - 计算技术指标；
        - 获取宏观数据；
        - 计算 Market Reaction；
        - 做 bullish / bearish 判断。

    它只负责：
        - 聚合已经计算好的结构化数据；
        - 保证 symbol 一致；
        - 保证数据没有超过 as_of；
        - 区分未请求和请求后缺失；
        - 保存数据质量报告和 warning。
    """

    model_config=ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    symbol: str = Field(min_length=1, max_length=10)
    as_of: AwareDatetime

    context_version: Literal[
        "market-context-v1"
    ] = MARKET_CONTEXT_VERSION

    # 本次问题实际需要哪些模块。
    requested_components: set[ContextComponent] = Field(min_length=1)

    # ---------- Market ----------
    quote: Quote | None = None

    technical: MarketTechnicalSnapshot | None = None

    # ---------- Macro ----------

    macro: MacroSnapshot | None = None

    #  Historical event reaction

    market_reaction: MarketReactionResult | None = None

    # ---------- Quality ----------

    quality_report: DataQualityReport | None = None

    # Provider、Builder 或上层组装过程中产生的非阻断 warning。
    warnings: list[str] = Field(
        default_factory=list,
    )

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().upper()

        if not normalized:
            raise ValueError("symbol must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        """检查整个研究上下文的数据归属与时间边界。"""

        # ----------------------------------------------------
        # 1. Quote
        # ----------------------------------------------------
        if self.quote is not None:
            quote_symbol = self.quote.symbol.strip().upper()
            if quote_symbol != self.symbol:
                raise ValueError("quote symbol does not match context symbol")

            if self.quote.quoted_at > self.as_of:
                raise ValueError("quote timestamp is after context as_of")

            if self.quote.received_at > self.as_of:
                raise ValueError("quote received_at is after context as_of")


        # ----------------------------------------------------
        # 2. Technical snapshot
        # ----------------------------------------------------

        if self.technical is not None:
            technical_symbol = self.technical.symbol.strip().upper()
            if technical_symbol != self.symbol:
                raise ValueError("technical symbol does not match context symbol")

            if self.technical.price_at is not None and self.technical.price_at > self.as_of:
                raise ValueError("technical price_at is after context as_of")

        # ----------------------------------------------------
        # 3. Macro snapshot
        # ----------------------------------------------------

        if self.macro is not None:
            if self.macro.as_of > self.as_of:
                raise ValueError("macro as_of is after context as_of")

        # ----------------------------------------------------
        # 4. Market Reaction
        # ----------------------------------------------------

        if self.market_reaction is not None:
            reaction_symbol = self.market_reaction.symbol.strip().upper()
            if reaction_symbol != self.symbol:
                raise ValueError("market reaction symbol does not match context symbol")

            if self.market_reaction.event_at is not None and self.market_reaction.event_at > self.as_of:
                raise ValueError("market reaction event_at is after context as_of")

            if self.market_reaction.reference_at is not None and  self.market_reaction.reference_at > self.as_of:
                raise ValueError("market reaction reference_at is after context as_of")

            for observation in self.market_reaction.observations.values():
                if observation.price_at is not None and observation.price_at > self.as_of:
                    raise ValueError("market reaction observation price_at is after context as_o")

        # ----------------------------------------------------
        # 5. Quality report
        # ----------------------------------------------------
        if self.quality_report is not None:
            if self.quality_report.as_of > self.as_of:
                raise ValueError("quality report as_of does not match context as_of")

        return self

    def _component_available(
        self,
        component: ContextComponent,
    ) -> bool:
        """判断某个组件实际上是否存在。"""
        if component == 'quote':
            return self.quote is not None

        if component == 'macro':
            return self.macro is not None

        if component == 'market_reaction':
            return self.market_reaction is not None

        if component == 'technical':
            return self.technical is not None

    # 数据有没有
    @computed_field
    @property
    def component_statuses(
        self,
    ) -> dict[
        ContextComponent,
        ContextComponentStatus,
    ]:
        """区分 available / missing / not_requested。"""
        statuses: dict[
            ContextComponent,
            ContextComponentStatus,
        ] = {}

        for component in COMPONENT_ORDER:
            if component not in self.requested_components:
                statuses[component] = "not_requested"
                continue
            if self._component_available(component):
                statuses[component] = 'available'
            else:
                statuses[component] = 'missing'
        return statuses

    @computed_field
    @property
    def missing_components(
        self,
    ) -> list[ContextComponent]:
        """只返回本次请求需要、但实际没有取得的数据。"""
        return [
            component
            for component in COMPONENT_ORDER
            if self.component_statuses[component] == 'missing'
        ]

    def _quality_status_for_component(
        self,
        component: ContextComponent,
    ) -> ComponentQualityStatus:
        """汇总某个 Context Component 的质量状态。"""
        # 本次研究根本没有请求这个模块。

        if component not in self.requested_components:
            return "not_requested"

        # 没有质量报告：
        # 只能说尚未评估，不能默认 usable。
        if self.quality_report is None:
            return "not_assessed"

        purpose = COMPONENT_QUALITY_PURPOSE[component]

        results = [
            result
            for result in self.quality_report.results
            if (
                result.purpose == purpose
                and (
                    component not in SYMBOL_SCOPED_COMPONENTS
                    or result.target_id.strip().upper() == self.symbol
                )
            )

        ]

        # 有 QualityReport，
        # 但没有对这个组件进行检查。
        if not results:
            return "not_assessed"

        statuses = {
            result.status
            for result in results
        }

        if statuses == {"usable"}:
            return "usable"

        if statuses == {"rejected"}:
            return "rejected"

        return "degraded"


    # 已经取得的数据质量如何
    @computed_field
    @property
    def component_quality_statuses(
        self,
    ) -> dict[
        ContextComponent,
        ComponentQualityStatus,
    ]:
        """按 Context Component 汇总数据质量状态。"""

        return {
            component: self._quality_status_for_component(
                component
            )
            for component in COMPONENT_ORDER
        }

    @computed_field
    @property
    def provenance(
        self,
    ) -> MarketContextProvenance:
        """汇总当前 Context 已保留下来的来源和版本。"""

        components: dict[
            ContextComponent,
            ComponentProvenance,
        ] = {}
        # ---------- Quote ----------

        if self.quote is not None:
            components["quote"] = (
                ComponentProvenance(
                    sources=(
                        self.quote.source,
                    ),
                )
            )

        # ---------- Technical ----------

        if self.technical is not None:
            components["technical"] = (
                ComponentProvenance(
                    sources=(
                        self.technical.input_sources
                    ),
                    versions=(
                        self.technical.calculation_version,
                    ),
                )
            )

        # ---------- Macro ----------

        if self.macro is not None:
            macro_sources: list[
                str | None
            ] = []

            for release in self.macro.recent_releases:
                macro_sources.extend([
                    release.release_date_source,
                    release.schedule_source,
                    release.released_at_source,
                ])

                for metric in release.metrics:
                    macro_sources.extend([
                        metric.source,
                        metric.consensus_source,
                    ])

            if self.macro.fed_policy is not None:
                macro_sources.append(
                    self.macro.fed_policy.current.source
                )

                if (
                    self.macro.fed_policy.previous
                    is not None
                ):
                    macro_sources.append(
                        self.macro.fed_policy.previous.source
                    )
            for projection in self.macro.fed_projections:
                macro_sources.append(
                    projection.source
                )

            if self.macro.treasury is not None:
                macro_sources.extend(
                    self.macro.treasury
                    .yield_sources.values()
                )

                if (
                    self.macro.treasury
                    .previous_yield_sources
                    is not None
                ):
                    macro_sources.extend(
                        self.macro.treasury
                        .previous_yield_sources
                        .values()
                    )

            components["macro"] = (
                ComponentProvenance(
                    sources=_unique_strings(
                        macro_sources
                    ),
                )
            )

        # ---------- Market Reaction ----------

        if self.market_reaction is not None:
            reaction_sources: list[
                str | None
            ] = [
                (
                    self.market_reaction
                    .event_time_source
                ),
                (
                    self.market_reaction
                    .reference_source
                ),
            ]

            reaction_sources.extend(
                observation.price_source
                for observation
                in self.market_reaction
                .observations.values()
            )

            components["market_reaction"] = (
                ComponentProvenance(
                    sources=_unique_strings(
                        reaction_sources
                    ),
                    versions=(
                        self.market_reaction
                        .calculation_version,
                    ),
                )
            )

        # ---------- Quality ----------

        quality_versions: tuple[str, ...] = ()

        if self.quality_report is not None:
            quality_versions = _unique_strings([
                result.rule_version
                for result
                in self.quality_report.results
            ])

        return MarketContextProvenance(
            as_of=self.as_of,

            context_version=(
                self.context_version
            ),

            components=components,

            quality_rule_versions=(
                quality_versions
            ),
        )


def _unique_strings(
    values: list[str | None],
) -> tuple[str, ...]:
    """去掉 None 和重复值，同时保持首次出现顺序。"""

    result: list[str] = []

    for value in values:
        if value is None:
            continue

        if value not in result:
            result.append(value)

    return tuple(result)

# ============================================================
# FactorOpinion
# ============================================================



FactorName = Literal[
    "trend",
    "momentum",
    "level",
]

FactorStatus = Literal[
    "usable",
    "insufficient_data",
    "blocked",
]

FactorSignal = Literal[
    "bullish",
    "bearish",
    "neutral",
    "mixed",
]


FactorEvidenceValue = (
    Decimal
    | bool
    | int
    | str
    | None
)

class FactorEvidence(BaseModel):
    """某个因子实际使用的一项结构化证据。

    例如：

        metric="ma5"
        value=Decimal("225.10")
        source="technical.ma5"

    Day32 的 Factor 不应该只返回一句文本理由，
    还应该保存实际参与规则判断的输入。

    Day34 进一步使用同一结构记录固定阈值和价格来源，
    source 可以指向 Technical 字段或具体规则版本。
    """
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    metric: str = Field(min_length=1)

    value: FactorEvidenceValue

    source: str = Field(min_length=1)


class FactorOpinion(BaseModel):
    """单个确定性分析因子的标准输出。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    factor: FactorName

    status: FactorStatus

    # 只有 status=usable 时才能给方向。
    signal: FactorSignal | None = None

    # Day32 每个 Factor 自己维护规则版本。
    rule_version: str = Field(
        min_length=1,
    )

    evidence: list[FactorEvidence] = Field(
        default_factory=list,
    )

    # 机器可读原因，例如：
    #
    # ma5_above_ma20
    # return_20d_positive
    # current_price_near_support
    reasons: list[str] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_factor_result(self) -> Self:

        if self.status == "usable":
            if self.signal is None:
                raise ValueError(
                    "usable factor requires signal"
                )

            if not self.reasons:
                raise ValueError(
                    "usable factor requires reasons"
                )

        else:
            if self.signal is not None:
                raise ValueError(
                    "non-usable factor must not "
                    "contain signal"
                )

        return self

# ============================================================
# DecisionResult
# ============================================================

DecisionStatus = Literal[
    "complete",
    "partial",
    "blocked",
]

MarketView = Literal[
    "bullish",
    "bearish",
    "neutral",
    "mixed",
]

class DecisionResult(BaseModel):
    """确定性市场分析引擎的标准输出。

    Day31 定义基础契约，Day32 / Day33 实现 Factor、Guard
    和综合规则。Day34 用 factors、decision_reasons、
    opposing_reasons 与 invalidation_conditions 组成公开、
    可复算的 Decision Trace。
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    symbol: str = Field(
        min_length=1,
        max_length=32,
    )

    as_of: AwareDatetime

    status: DecisionStatus

    # blocked 时必须为 None。
    market_view: MarketView | None = None

    rule_version: str = Field(
        min_length=1,
    )

    factors: list[FactorOpinion] = Field(
        default_factory=list,
    )

    # Decision 层的组合规则为什么得到当前 market_view。
    #
    # 这里只记录 Decision 层的规则路径，
    # 不重复保存 Factor 自己的指标和判断依据。
    #
    # 例如：
    # - primary_factors_aligned
    # - trend_momentum_conflict
    # - trend_direction_retained_without_momentum_confirmation
    # - level_conflicts_with_primary_direction
    decision_reasons: list[str] = Field(
        default_factory=list,
    )

    missing_information: list[str] = Field(
        default_factory=list,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    # 明确方向中仍然存在的反面或未确认信息。
    opposing_reasons: list[str] = Field(
        default_factory=list,
    )

    # 哪些可观察变化会使当前判断依据失效并要求重新评估。
    invalidation_conditions: list[str] = Field(
        default_factory=list,
    )

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(
        cls,
        value: str,
    ) -> str:
        normalized = value.strip().upper()

        if not normalized:
            raise ValueError(
                "symbol must not be empty"
            )

        return normalized

    @model_validator(mode="after")
    def validate_decision(self) -> Self:

        if self.status == "blocked":
            if self.market_view is not None:
                raise ValueError(
                    "blocked decision must not "
                    "contain market_view"
                )

            if (
                self.decision_reasons
                or self.opposing_reasons
                or self.invalidation_conditions
            ):
                raise ValueError(
                    "blocked decision must not contain "
                    "directional trace"
                )

        else:
            if self.market_view is None:
                raise ValueError(
                    "complete/partial decision "
                    "requires market_view"
                )

            if not self.decision_reasons:
                raise ValueError(
                    "complete/partial decision requires "
                    "decision_reasons"
                )

        factor_names = [
            factor.factor
            for factor in self.factors
        ]

        if len(factor_names) != len(set(factor_names)):
            raise ValueError(
                "duplicate factor opinion"
            )

        return self
