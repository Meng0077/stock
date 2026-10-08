import re
from typing import Any

from stock_agent.agents.langgraph.state import (
    ResearchPlan,
    ResearchState,
)
from stock_agent.macro.models.release import (
    MacroReleaseType,
)
from stock_agent.schemas.research import (
    ResearchRequest,
)


DEFAULT_HISTORY_LIMIT = 5


PLANNER_PROMPT = """
你是股票研究工作流的 Planner。

你的职责只有：

把用户的 ResearchRequest
转换成一个完整的 ResearchPlan。

ResearchPlan 是多能力组合，
不是单选路由。

一个问题可以同时需要：

- Company Profile
- Quote
- Technical
- Decision
- Knowledge
- Financial
- Macro
- 最新 Macro Reaction
- 历史 Macro Reaction
- 最新 Earnings Reaction
- 历史 Earnings Reaction

你必须完整识别用户问题中的所有研究需求，
不能因为识别出一种能力，
就忽略问题中的其他部分。

你不负责：
- 回答用户问题；
- 调用工具；
- 查询数据；
- 计算技术指标；
- 判断 bullish / bearish；
- 修改确定性业务结果。


各字段含义如下。


needs_company_profile：

用户需要公司基础资料时为 true。


needs_quote：

用户明确询问当前报价、现价时为 true。


needs_technical：

用户需要具体技术指标、技术结构时为 true。

例如：
- MA20 / MA50 / MA200；
- RSI；
- ATR；
- 支撑；
- 阻力；
- 当前价格位置。


needs_decision：

用户需要整体技术观点时为 true。

例如：
- 技术面怎么看；
- 当前走势如何；
- 偏多还是偏空；
- 趋势和动能是否一致；
- 技术观点失效条件。

不得自行生成 market_view。


knowledge_question：

用户需要公司文档或 SEC filing
中的文本解释时，
填写具体检索问题。

不需要时为 null。


financial_requests：

用户需要结构化财务数字时填写。

每项包含：
- concept；
- unit；
- period_type。

不需要时为空列表。


needs_macro：

用户需要当前系统支持的宏观数据时为 true。

具体 release type 当前包括：
- cpi；
- ppi；
- employment_situation；
- pce；
- weekly_claims。


macro_release_type：

针对具体宏观事件时填写 release type。

如果只研究整体宏观环境，
可以为 null。


needs_macro_reaction：

用户需要最近一次 / 当前这一次
宏观发布后的实际价格反应时为 true。


needs_macro_reaction_history：

用户需要之前若干次同类宏观发布后的
历史价格反应时为 true。


macro_reaction_history_limit：

如果需要历史宏观反应，
填写需要研究的事件数量。

如果用户没有明确数量，
使用 5。

不需要历史反应时必须为 null。


needs_earnings_reaction：

用户需要最近一次 / 当前这一次
财报披露后的实际价格反应时为 true。


needs_earnings_reaction_history：

用户需要之前若干次财报披露后的
历史价格反应时为 true。


earnings_reaction_history_limit：

如果需要历史财报反应，
填写需要研究的事件数量。

如果用户没有明确数量，
使用 5。

不需要历史财报反应时必须为 null。


例如：

“这次 CPI 后 NVDA 怎么走，
之前 5 次 CPI 后又怎么走，
结合当前技术面分析”

应该同时包括：

- needs_macro=true
- macro_release_type="cpi"
- needs_macro_reaction=true
- needs_macro_reaction_history=true
- macro_reaction_history_limit=5
- needs_technical=true
- needs_decision=true


例如：

“这次财报为什么数据中心增长，
财报后 NVDA 怎么走，
再看看过去 3 次财报后的表现”

应该同时包括：

- knowledge_question 非 null
- needs_earnings_reaction=true
- needs_earnings_reaction_history=true
- earnings_reaction_history_limit=3


不要为了保险开启无关能力。
"""


_CHINESE_HISTORY_NUMBERS = {
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def extract_history_limit(
    question: str,
) -> int:
    """
    从“过去 3 次 / 前五次”这类表达中
    提取历史事件数量。

    没有明确数量时使用默认值 5。
    """

    digit_match = re.search(
        r"(?:过去|之前|最近|前|历史)"
        r"\s*(\d+)\s*次",
        question,
    )

    if digit_match is not None:
        return int(
            digit_match.group(1)
        )

    chinese_match = re.search(
        r"(?:过去|之前|最近|前|历史)"
        r"\s*([两二三四五六七八九十])\s*次",
        question,
    )

    if chinese_match is not None:
        return _CHINESE_HISTORY_NUMBERS[
            chinese_match.group(1)
        ]

    return DEFAULT_HISTORY_LIMIT


def detect_macro_release_type(
    question: str,
) -> MacroReleaseType | None:
    """
    识别明确的宏观发布类型。

    只处理当前系统已有的
    MacroReleaseType。
    """

    if "cpi" in question:
        return "cpi"

    if "ppi" in question:
        return "ppi"

    if "pce" in question:
        return "pce"

    if (
        "非农" in question
        or "就业报告" in question
        or "employment situation"
        in question
    ):
        return "employment_situation"

    if (
        "初请" in question
        or "续请" in question
        or "失业金" in question
        or "weekly claims" in question
    ):
        return "weekly_claims"

    return None


def build_deterministic_plan(
    request: ResearchRequest,
) -> ResearchPlan | None:
    """
    对低歧义问题组合多个研究意图。

    返回：
    - ResearchPlan：
      当前问题可以由代码可靠识别；
    - None：
      存在需要自然语言语义理解的内容，
      交给 LLM Planner。

    重要：
    这里不是 first-match router。
    所有确定性 intent 都先收集，
    最后统一组成一个 Plan。
    """

    question = (
        request.question
        .strip()
        .lower()
    )

    # -------------------------------------------------
    # 1. 判断是否需要完整 LLM 语义规划。
    #
    # Financial / Knowledge 需要理解用户实际想问什么，
    # 第一版不靠关键词自己猜 XBRL concept
    # 或文档检索问题。
    # -------------------------------------------------

    semantic_markers = (
        "为什么",
        "原因",
        "解释",
        "管理层",
        "风险",
        "数据中心",
        "毛利率",
        "营收",
        "收入",
        "净利润",
        "eps",
        "revenue",
        "net income",
    )

    if any(
        marker in question
        for marker in semantic_markers
    ):
        return None

    # -------------------------------------------------
    # 2. 初始化所有独立 intent。
    # -------------------------------------------------

    needs_company_profile = False
    needs_quote = False

    needs_technical = False
    needs_decision = False

    needs_macro = False

    macro_release_type = (
        detect_macro_release_type(
            question
        )
    )

    needs_macro_reaction = False

    needs_macro_reaction_history = False

    macro_reaction_history_limit = None

    needs_earnings_reaction = False

    needs_earnings_reaction_history = False

    earnings_reaction_history_limit = None

    # -------------------------------------------------
    # 3. Company Profile
    # -------------------------------------------------

    company_profile_markers = (
        "公司是做什么",
        "主营业务",
        "公司简介",
        "company profile",
    )

    needs_company_profile = any(
        marker in question
        for marker in company_profile_markers
    )

    # -------------------------------------------------
    # 4. Quote
    # -------------------------------------------------

    quote_markers = (
        "现在多少钱",
        "当前多少钱",
        "当前股价",
        "现价",
        "报价",
        "current price",
        "quote",
    )

    needs_quote = any(
        marker in question
        for marker in quote_markers
    )

    # -------------------------------------------------
    # 5. Technical / Decision
    # -------------------------------------------------

    technical_metric_markers = (
        "rsi",
        "ma20",
        "ma50",
        "ma200",
        "atr",
        "均线",
        "支撑位",
        "阻力位",
        "支撑",
        "阻力",
        "技术指标",
    )

    technical_analysis_markers = (
        "技术分析",
        "技术层面",
        "结合技术面",
        "从技术面",
    )

    decision_markers = (
        "当前走势",
        "技术面怎么看",
        "技术面如何",
        "偏多",
        "偏空",
        "趋势怎么样",
        "动能怎么样",
        "失效条件",
        "market view",
    )

    needs_technical = any(
        marker in question
        for marker in technical_metric_markers
    )

    asks_full_technical_analysis = any(
        marker in question
        for marker in technical_analysis_markers
    )

    if asks_full_technical_analysis:
        needs_technical = True
        needs_decision = True

    if any(
        marker in question
        for marker in decision_markers
    ):
        needs_decision = True

    # -------------------------------------------------
    # 6. Event Reaction 公共语义
    # -------------------------------------------------

    reaction_markers = (
        "发布后",
        "公布后",
        "披露后",
        "财报后",
        "之后怎么走",
        "后的走势",
        "后的表现",
        "市场反应",
        "涨了多少",
        "跌了多少",
    )

    asks_reaction = (
        any(
            marker in question
            for marker in reaction_markers
        )
        or re.search(
            r"后.*(?:怎么走|走势|表现|市场反应)",
            question,
        )
        is not None
    )

    history_markers = (
        "之前几次",
        "过去几次",
        "最近几次",
        "历史几次",
        "前几次",
        "之前的",
        "过去的",
        "历史上",
        "historical",
        "previous releases",
        "previous earnings",
    )

    asks_history = (
        any(
            marker in question
            for marker in history_markers
        )
        or re.search(
            r"(?:过去|之前|最近|前|历史)"
            r"\s*(?:\d+|[两二三四五六七八九十])"
            r"\s*次",
            question,
        )
        is not None
    )

    current_event_markers = (
        "这次",
        "本次",
        "最近一次",
        "最新一次",
    )

    asks_current_event = any(
        marker in question
        for marker in current_event_markers
    )

    # -------------------------------------------------
    # 7. Macro
    # -------------------------------------------------

    if macro_release_type is not None:
        needs_macro = True

        if asks_reaction:
            # “过去几次 CPI 后”
            # 只需要历史反应。
            if asks_history:
                needs_macro_reaction_history = (
                    True
                )

                macro_reaction_history_limit = (
                    extract_history_limit(
                        question
                    )
                )

            # “这次 CPI 后”
            # 或普通“最近 CPI 后”
            # 需要最新一次反应。
            if (
                asks_current_event
                or not asks_history
            ):
                needs_macro_reaction = True

    # -------------------------------------------------
    # 8. Earnings
    # -------------------------------------------------

    earnings_markers = (
        "财报",
        "业绩",
        "earnings",
    )

    mentions_earnings = any(
        marker in question
        for marker in earnings_markers
    )

    if (
        mentions_earnings
        and asks_reaction
    ):
        if asks_history:
            needs_earnings_reaction_history = (
                True
            )

            earnings_reaction_history_limit = (
                extract_history_limit(
                    question
                )
            )

        if (
            asks_current_event
            or not asks_history
        ):
            needs_earnings_reaction = True

    # -------------------------------------------------
    # 9. 如果完全没有识别出明确意图，
    #    才交给 LLM。
    # -------------------------------------------------

    has_deterministic_intent = any(
        (
            needs_company_profile,
            needs_quote,
            needs_technical,
            needs_decision,
            needs_macro,
            needs_earnings_reaction,
            needs_earnings_reaction_history,
        )
    )

    if not has_deterministic_intent:
        return None

    # -------------------------------------------------
    # 10. 所有 intent 一次性组合。
    # -------------------------------------------------

    return ResearchPlan(
        needs_company_profile=(
            needs_company_profile
        ),
        needs_quote=needs_quote,
        needs_technical=needs_technical,
        needs_decision=needs_decision,

        knowledge_question=None,
        financial_requests=[],

        needs_macro=needs_macro,
        macro_release_type=(
            macro_release_type
        ),
        needs_macro_reaction=(
            needs_macro_reaction
        ),
        needs_macro_reaction_history=(
            needs_macro_reaction_history
        ),
        macro_reaction_history_limit=(
            macro_reaction_history_limit
        ),

        needs_earnings_reaction=(
            needs_earnings_reaction
        ),
        needs_earnings_reaction_history=(
            needs_earnings_reaction_history
        ),
        earnings_reaction_history_limit=(
            earnings_reaction_history_limit
        ),
    )


async def plan_with_model(
    request: ResearchRequest,
    *,
    model: Any,
) -> ResearchPlan:
    """
    确定性 Planner 无法可靠理解时，
    使用 LLM 做完整语义规划。
    """

    planner = model.with_structured_output(
        ResearchPlan
    )

    plan = await planner.ainvoke(
        [
            {
                "role": "system",
                "content": PLANNER_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    request.model_dump_json()
                ),
            },
        ]
    )

    return plan


async def plan_node(
    state: ResearchState,
    *,
    model: Any,
) -> dict[str, ResearchPlan]:
    """
    生成完整 ResearchPlan。

    优先使用确定性组合式 Planner；
    无法可靠理解时才调用 LLM。
    """

    request = state["request"]

    plan = build_deterministic_plan(
        request
    )

    if plan is None:
        plan = await plan_with_model(
            request,
            model=model,
        )

    return {
        "plan": plan,
    }
