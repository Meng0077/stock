from typing import (
    Annotated,
    Literal,
    Self,
    TypedDict,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    model_validator,
)

from stock_agent.financial.service import (
    FinancialPeriodType,
)
from stock_agent.macro.models.release import (
    MacroReleaseType,
)
from stock_agent.schemas.research import (
    ResearchRequest,
)

class FinancialResearchRequest(BaseModel):
    """
    Planner 对一次结构化财务查询的描述。

    这些字段最终可以直接交给
    get_financial_facts() 使用。
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    concept: str = Field(
        min_length=1,
    )

    unit: str = Field(
        min_length=1,
    )

    period_type: FinancialPeriodType

class ResearchPlan(BaseModel):
    """
    一次研究任务需要哪些研究能力。

    这是声明式 Plan：
    只描述“用户需要研究什么”，
    不描述具体函数调用顺序。
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    # -----------------------------
    # Company / Quote
    # -----------------------------

    needs_company_profile: StrictBool

    needs_quote: StrictBool

    # -----------------------------
    # Technical
    # -----------------------------

    # MA / RSI / ATR / 支撑阻力等具体技术结果。
    needs_technical: StrictBool

    # 当前整体技术观点。
    needs_decision: StrictBool

    # -----------------------------
    # Knowledge / Financial
    # -----------------------------

    # None：
    # 不需要文档检索。
    #
    # 非 None：
    # 直接作为 retrieve_knowledge()
    # 的研究问题。
    knowledge_question: (
        Annotated[
            str,
            Field(min_length=1),
        ]
        | None
    )

    # 空列表表示不需要结构化财务数据。
    financial_requests: list[
        FinancialResearchRequest
    ]

    # -----------------------------
    # Macro
    # -----------------------------

    # 是否需要宏观数据本身。
    needs_macro: StrictBool

    # 具体宏观发布类型。
    #
    # None 可以表示：
    # - 不需要 Macro；
    # - 或需要整体 MacroSnapshot。
    #
    # 由 needs_macro 区分。
    macro_release_type: (
        MacroReleaseType | None
    )

    # 最近一次 / 指定当前事件的市场反应。
    needs_macro_reaction: StrictBool

    # 最近若干次同类事件的历史反应。
    needs_macro_reaction_history: StrictBool

    # 历史反应查询次数。
    #
    # 字段本身必须由 Planner 明确输出，
    # 但允许值为 None。
    macro_reaction_history_limit: (
        Annotated[
            int,
            Field(ge=1, le=20),
        ]
        | None
    )

    # -----------------------------
    # Earnings
    # -----------------------------

    # 最近一次已确认财报事件后的反应。
    needs_earnings_reaction: StrictBool

    # 最近若干次财报事件后的历史反应。
    needs_earnings_reaction_history: StrictBool

    earnings_reaction_history_limit: (
        Annotated[
            int,
            Field(ge=1, le=20),
        ]
        | None
    )

    @model_validator(mode="after")
    def validate_macro_plan(
        self,
    ) -> Self:
        """
        校验 Macro 相关字段之间的依赖关系。
        """

        if (
            not self.needs_macro
            and self.macro_release_type
            is not None
        ):
            raise ValueError(
                "macro_release_type requires "
                "needs_macro=True"
            )

        needs_any_macro_reaction = (
            self.needs_macro_reaction
            or
            self.needs_macro_reaction_history
        )

        if needs_any_macro_reaction:
            if not self.needs_macro:
                raise ValueError(
                    "macro reaction requires "
                    "needs_macro=True"
                )

            if (
                self.macro_release_type
                is None
            ):
                raise ValueError(
                    "macro reaction requires "
                    "a concrete macro_release_type"
                )

        if self.needs_macro_reaction_history:
            if (
                self.macro_reaction_history_limit
                is None
            ):
                raise ValueError(
                    "historical macro reaction "
                    "requires history limit"
                )

        elif (
            self.macro_reaction_history_limit
            is not None
        ):
            raise ValueError(
                "macro_reaction_history_limit "
                "requires historical "
                "macro reaction"
            )

        return self

    @model_validator(mode="after")
    def validate_earnings_plan(
        self,
    ) -> Self:
        """
        校验 Earnings 历史反应字段。
        """

        if (
            self.needs_earnings_reaction_history
        ):
            if (
                self.earnings_reaction_history_limit
                is None
            ):
                raise ValueError(
                    "historical earnings reaction "
                    "requires history limit"
                )

        elif (
            self.earnings_reaction_history_limit
            is not None
        ):
            raise ValueError(
                "earnings_reaction_history_limit "
                "requires historical "
                "earnings reaction"
            )

        return self

ResearchStatus = Literal[
    "enough",
    "retry",
    "cannot_retry",
]

class ResearchState(TypedDict):
    """
    Day36 LangGraph 的共享运行状态。
    """

    request: ResearchRequest

    plan: ResearchPlan | None

    results: dict[str, object]

    missing_information: list[str]

    retry_count: int

    research_status: ResearchStatus | None

    output: str | None
