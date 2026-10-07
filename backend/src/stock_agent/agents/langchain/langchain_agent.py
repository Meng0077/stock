"""D07/D09：组装 LangChain Agent，并校验结构化结果、记录运行终态。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
from typing import TYPE_CHECKING, Any, cast
import uuid

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallLimitMiddleware,
    wrap_model_call,
)
from langchain.messages import AIMessage

from stock_agent.agents.evidence import (
    collect_evidence_data_modes,
    validate_evidence,
    collect_evidence_ids,
)
from stock_agent.documents.sec_http import SEC_CLIENT
from stock_agent.storage.database import create_database_engine
from stock_agent.agents.context import ResearchContext
from stock_agent.agents.structured_output import (
    EvidenceValidationError,
    IncompleteResponseError,
)
from stock_agent.schemas.errors import make_public_error, map_error
from stock_agent.agents.langchain.langchain_tools import (
    build_langchain_tools,
    collect_tool_events,
)
from stock_agent.agents.langchain.tool_middleware import handle_tool_errors
from stock_agent.schemas.research import ResearchRequest

if TYPE_CHECKING:
    from stock_agent.schemas.research_output import ResearchOutput

SYSTEM_PROMPT = """
你是只读的股票教学研究助手。

回答股票相关事实时，必须优先使用提供的工具获取证据，
不要仅依赖模型记忆回答公司事实。

对于收入、净利润、资产、股东权益等明确的结构化财务数值，
优先使用 Financial Tool，不要仅依靠 Filing 文本推测数值。

对于管理层解释、业务原因、风险因素、MD&A 等文本信息，
使用 Knowledge Tool。

如果用户的问题同时要求财务数值和文本解释，
可以同时调用 Financial Tool 和 Knowledge Tool。

工具使用规则：

1. 当问题涉及股票报价、价格或行情时，使用 get_quote。

2. 当问题涉及公司业务、产品、战略、风险、竞争情况、
   财报内容或其他公司文档信息时，使用 retrieve_knowledge。

3. 如果一个问题同时涉及报价和公司业务信息，
   可以同时使用 get_quote 和 retrieve_knowledge。

3.1 get_quote 返回的 quality 表示报价的数据质量。

    usable：
    可以在注明报价时间和交易时段的前提下使用。

    degraded：
    可以展示报价，但必须明确说明质量问题。
    不得将延迟状态未知、市场状态未知或休市报价
    描述为经过验证的实时价格。

    rejected：
    quote 为 null，不得编造价格，也不得为该次查询
    生成报价事实。

4. retrieve_knowledge 的 company_id 必须使用请求中的公司代码。
   question 应描述需要检索的具体信息。

5. 最终输出中的 facts 和 inferences 只能引用本轮工具实际返回的 evidence_id。

6. 如果现有工具返回的信息不足以回答问题，
   返回 insufficient_information，不要编造缺失事实。

7. 最终 data_mode 根据实际引用的证据填写：只引用一种模式就使用该模式；
   同时引用不同模式时使用 mixed；没有引用任何证据时使用 null。

8. 当问题涉及 CPI、PPI、PCE、就业、失业金申领、FOMC、SEP、
   美债收益率或宏观 Surprise 时，使用 get_macro_snapshot。
   查询单个发布时传 release_type；需要 Fed、SEP、美债或整体环境时不传。

9. 宏观工具中的 consensus、estimated_surprise 和 surprise 含义不同，
   必须保持工具返回的字段名称与数值，不能把 estimated_surprise 表述为
   已通过严格历史验证的 surprise。

10. 当问题只涉及当前报价时，使用 get_quote。

    当问题涉及 MA5、MA20、MA50、MA200、均线斜率、ATR、历史收益率、
    支撑阻力、价格缺口或成交量特征时，
    使用 get_technical_analysis。

    当问题涉及当前报价与历史技术指标的比较时，
    优先使用 get_technical_analysis。

    必须根据 quality 中的具体检查结果使用数据。
    quote 为 null 时，不得将历史收盘价称为实时价格。
    technical 为 null 时，不得编造技术指标。
    degraded 状态下，必须说明对应的数据限制。

    Quote 和技术指标拥有不同的 evidence_id。
    当一个结论同时依赖两者时，应同时引用两份证据。
11. 当用户询问股票当前整体技术走势、技术观点、偏多偏空、
    趋势与动能是否一致、当前观点的反对因素或失效条件时，
    使用 evaluate_market。

    例如：
    - “NVDA 当前走势如何？”
    - “NVDA 技术面现在怎么看？”
    - “NVDA 当前偏多还是偏空？”
    - “当前判断什么时候会失效？”

    evaluate_market 返回的是确定性 Decision Engine 的结果。

    必须遵守：
    - status == blocked 时，不得自行给出 bullish、bearish、
      neutral 或 mixed 等方向结论；
    - market_view 不得被模型重新计算或改写；
    - factors、decision_reasons、opposing_reasons、
      invalidation_conditions 可以翻译成自然语言，
      但不能改变其业务含义；
    - 不得根据 MA、RSI 或其他工具结果，
      覆盖 evaluate_market 已经给出的 market_view。


12. 当用户只询问具体技术指标或价格结构时，
    使用 get_technical_analysis。

    例如：
    - MA20 / MA50 是多少；
    - RSI14 是多少；
    - ATR 是多少；
    - 当前支撑、阻力在哪里；
    - 当前价格相对 20 日高低点的位置。

    不要仅因为用户询问某个具体指标，
    就强制调用 evaluate_market。

    如果问题既要求具体指标，
    又要求整体技术观点，
    可以同时使用 get_technical_analysis 和 evaluate_market。


13. 当用户询问某次宏观数据发布之后股票实际发生了什么变化时，
    使用 get_market_reaction。

    get_market_reaction 必须使用具体的 release_id。

    如果用户只给出事件类型，例如：
    “最近一次 CPI 后 NVDA 怎么走？”

    应先使用 get_macro_snapshot 获取可用的具体发布事件和 release_id，
    再调用 get_market_reaction。


14. Market Reaction 只描述事件前后实际观察到的价格变化。

    不得把时间上的先后关系表述成已经证明的因果关系。

    可以说：
    “CPI 发布后 30 分钟内 NVDA 下跌 1.2%。”

    不应直接说：
    “CPI 导致 NVDA 下跌 1.2%。”

    除非存在其他独立证据支持因果判断。


15. 必须严格保留 Market Reaction observation 的状态。

    usable：
    可以引用实际 price / return_pct。

    pending：
    观察窗口尚未形成，不能把它描述成 0%、缺失或已经完成。

    missing：
    对应窗口本应已经形成，但缺少可用行情。

    unavailable：
    当前数据能力或前置条件不足，不能伪造收益率。


16. 工具返回的数值、时间、状态和确定性业务结论不得由模型修改。

    包括但不限于：
    - Quote.price
    - MA / RSI / ATR
    - Macro actual / consensus / estimated_surprise
    - MarketReaction reference_price / return_pct
    - DecisionResult.status
    - DecisionResult.market_view

    模型可以负责：
    - 组织内容；
    - 翻译机器可读 reason；
    - 解释不同证据之间的关系。

    模型不负责：
    - 重新计算工具数值；
    - 用自己的判断覆盖 Guard；
    - 修改确定性 Decision 的方向；
    - 将 unavailable / pending 数据补成具体结果。


17. 技术 Decision、财报内容、宏观数据和 Market Reaction 保持独立。

    不要自行创建未经定义的综合评分、
    confidence、上涨概率或胜率。

    例如，一个回答可以同时说明：

    - 当前 Technical Decision 为 bullish；
    - 最近一次财报 Revenue 为某个工具返回值；
    - CPI actual 高于 consensus；
    - CPI 发布后 NVDA 30 分钟下跌 1.2%；
    - 财报披露后 NVDA 30 分钟上涨 2.0%。

    但不能自行把这些内容计算成：
    “综合看涨概率 72%”。

18. 当问题涉及财报本身的内容时，
    根据问题类型使用 Financial Tool 或 Knowledge Tool。

    对结构化财务数值，例如：
    - revenue；
    - net income；
    - assets；
    - EPS 等可用结构化财务事实；
    优先使用 get_financial_facts。

    对财报文本内容，例如：
    - 管理层解释；
    - 业务增长原因；
    - 风险；
    - MD&A；
    - 产品与业务描述；
    使用 retrieve_knowledge。

    如果用户同时需要财务数值和管理层解释，
    可以同时使用 get_financial_facts 和 retrieve_knowledge。


19. 当用户询问最近一次财报披露之后股票实际怎么走时，
    使用 get_earnings_market_reaction。

    例如：
    - “NVDA 这次财报后怎么走？”
    - “最近一次财报发布后 NVDA 涨了多少？”
    - “NVDA 财报后 30 分钟表现怎么样？”
    - “财报披露后下一个正式交易日收盘表现如何？”

    get_earnings_market_reaction 会自行识别
    as_of 之前最近一次可确认的 Earnings 8-K，
    模型不得自行猜测财报事件时间或 event_id。

    当前第一版财报事件使用：
    SEC 8-K Item 2.02
    并以 SEC accepted_at 作为事件时间基准。

    如果工具返回：
    event_time_uses_sec_8k_acceptance

    回答中必须明确：
    市场反应窗口以 SEC 8-K 的公开接收时间为基准，
    不能把该时间描述为已经验证的公司最早新闻稿发布时间。


20. “财报内容”与“财报后的市场反应”是两个独立问题。

    例如用户问：

    “这次 NVDA 财报怎么样，市场又是怎么反应的？”

    应根据需要组合：

    get_financial_facts
    retrieve_knowledge
    get_earnings_market_reaction

    其中：

    Financial / Knowledge
    → 回答财报本身披露了什么；

    get_earnings_market_reaction
    → 回答披露之后实际观察到的股价变化。

    不得因为财报数据好，就自行推导股价应该上涨；
    也不得因为股价下跌，就改写财报本身的结构化事实。


21. Earnings Market Reaction 与 Macro Market Reaction
    遵守相同的 observation 规则。

    usable：
    可以引用实际 price 和 return_pct。

    pending：
    观察窗口尚未形成。

    missing：
    该窗口本应形成，但行情缺失。

    unavailable：
    当前数据或前置条件不足。

    不得把 pending / missing / unavailable
    补写成模型猜测的价格或收益率。


22. Earnings Market Reaction 只证明事件时间前后观察到的市场变化，
    不证明财报内容与价格变化之间存在确定因果关系。

    可以说：

    “以 SEC 8-K accepted_at 为事件时间，
    NVDA 在财报披露后 30 分钟上涨 2.1%。”

    不应仅根据该结果说：

    “财报导致 NVDA 上涨 2.1%。”
"""


MAX_MODEL_ROUNDS = 3
MAX_TOOL_CALLS = 4

TASK_TIMEOUT_SECONDS = 300


@wrap_model_call
async def reject_truncated_response(
    request: ModelRequest,
    handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
) -> ModelResponse:
    """模型节点提交结果前拒绝截断，不继续工具执行或下一轮格式修复。"""
    response = await handler(request)
    for message in response.result:
        if isinstance(message, AIMessage) and message.response_metadata.get("finish_reason") == "length":
            raise IncompleteResponseError("模型响应被截断")
    return response


def build_agent_input(
    request: ResearchRequest,
) -> dict[str, list[dict[str, str]]]:
    """把 ResearchRequest 转成 Agent 输入。"""

    return {
        "messages": [
            {
                "role": "user",
                "content": request.model_dump_json(),
            }
        ]
    }


def build_langchain_agent(
    model: Any,
    response_format = None
) -> Any:
    """创建 LangChain Agent，提供只读研究工具。"""

    middleware = cast(
        list[AgentMiddleware[Any, ResearchContext, Any]],
        [
            handle_tool_errors,
            ModelCallLimitMiddleware(
                run_limit=MAX_MODEL_ROUNDS,
                exit_behavior="error"
            ),
            ToolCallLimitMiddleware(
                run_limit=MAX_TOOL_CALLS,
                exit_behavior="error"
            ),
            reject_truncated_response,
        ],
    )

    return create_agent(
        model=model,
        tools=build_langchain_tools(),
        context_schema=ResearchContext,
        system_prompt=SYSTEM_PROMPT,
        response_format=response_format,
        middleware=middleware,

    )


async def invoke_langchain_agent(
    agent: Any,
    request: ResearchRequest,
    engine=None,
    macro_builder_factory=None,
    market_provider_factory=None,
) -> dict[str, Any]:
    """运行 Agent。"""
    async with asyncio.timeout(TASK_TIMEOUT_SECONDS):
        return await agent.ainvoke(
            build_agent_input(request),
            context=ResearchContext(
                as_of=request.as_of,
                engine=engine,
                sec_client=SEC_CLIENT,
                macro_builder_factory=macro_builder_factory,
                market_provider_factory=market_provider_factory,
                ),
        )


async def run_research(
    agent,
    request: ResearchRequest,
    engine=None,
    macro_builder_factory=None,
    market_provider_factory=None,
):
    """运行边界：统一返回运行身份、终态、结果、安全错误和事件。"""
    run_id = str(uuid.uuid4())
    events: list[dict[str, Any]] = [
        {"type": "run_started", "run_id": run_id}
    ]
    latest_state: dict[str, Any] = build_agent_input(request)
    runtime_error: Exception | None = None
    try:
        async with asyncio.timeout(TASK_TIMEOUT_SECONDS):
            async for state in agent.astream(
                latest_state,
                stream_mode="values",
                context=ResearchContext(
                        as_of=request.as_of,
                        engine=engine,
                        sec_client=SEC_CLIENT,
                        macro_builder_factory=macro_builder_factory,
                        market_provider_factory=market_provider_factory,
                    ),
            ):
                latest_state = state
    # 此运行边界负责把 runtime 异常转换成不含原始异常的公开失败。
    except Exception as error:
        runtime_error = error

    events.extend(collect_tool_events(latest_state["messages"], run_id))
    output: ResearchOutput | None = None
    public_error: dict[str, Any] | None = None
    if runtime_error is not None:
        public_error = make_public_error(map_error(runtime_error)).model_dump()
    else:
        output = cast(
            "ResearchOutput",
            latest_state["structured_response"],
        )

        # print(
        #     json.dumps(
        #         output,
        #         ensure_ascii=False,
        #         indent=2,
        #         default=str,
        #     )
        # )

        try:
            allowed_ids = collect_evidence_ids(latest_state["messages"])
            evidence_modes = collect_evidence_data_modes(latest_state["messages"])
            if engine is None and any(
                evidence_id.startswith(("rag:", "financial:"))
                for evidence_id in allowed_ids
            ):
                engine = create_database_engine()
            validate_evidence(
                output,
                allowed_ids,
                evidence_modes,
                request.data_mode,
                engine=engine
            )
        except EvidenceValidationError as error:
            public_error = make_public_error(map_error(error)).model_dump()
            output = None

    if public_error is not None:
        status = "failed"
    else:
        assert output is not None
        status = output.status
    events.append({
        "type": "run_finished",
        "run_id": run_id,
        "status": status,
        "error": public_error,
    })

    return {
        "run_id": run_id,
        "status": status,
        "output": output,
        "error": public_error,
        "events": events,
    }
