"""Day36 LangGraph + Longbridge 真实行情验收。

真实调用 Longbridge Quote 和 Daily Bars，
不调用真实模型，不提交交易订单。

运行：
PYTHONPATH=backend/src backend/.venv/bin/python \
    evals/verify_day36_longbridge_workflow.py
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from langchain.messages import AIMessage
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)

from stock_agent.agents.context import ResearchContext
from stock_agent.agents.langgraph import (
    build_initial_state,
    build_research_graph,
)
from stock_agent.market.longbridge.config_factory import (
    build_longbridge_market_provider,
)
from stock_agent.schemas.research import ResearchRequest


ROOT = Path(__file__).resolve().parents[1]
SYMBOL = "NVDA"


class RecordingMarketProvider:
    """记录 Graph 对真实 Longbridge Provider 的调用次数。"""

    def __init__(self):
        self.provider = build_longbridge_market_provider()
        self.quote_calls = 0
        self.bar_calls = 0

    def get_quote(self, *args, **kwargs):
        self.quote_calls += 1
        return self.provider.get_quote(*args, **kwargs)

    def get_bars(self, *args, **kwargs):
        self.bar_calls += 1
        return self.provider.get_bars(*args, **kwargs)

    def get_intraday_bars(self, *args, **kwargs):
        raise AssertionError(
            "Day36 market workflow must not request intraday bars"
        )

    def reset_counts(self) -> None:
        self.quote_calls = 0
        self.bar_calls = 0


async def verify_day36_longbridge_workflow() -> None:
    """验证真实 Quote-only 与 Technical/Decision 组合流程。"""

    load_dotenv(ROOT / "backend" / ".env", override=False)

    # 给实时请求和本地接收时间留出网络调用窗口。
    as_of = datetime.now(timezone.utc) + timedelta(minutes=1)
    provider = RecordingMarketProvider()
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(content="NVDA 真实报价流程已完成。"),
            AIMessage(content="NVDA 技术与观点流程已完成。"),
        ]
    )
    graph = build_research_graph(model)
    context = ResearchContext(
        as_of=as_of,
        market_provider_factory=lambda: provider,
        # 联调可能在休市期间运行，不把休市报价误判成实时价格。
        market_state="closed",
    )

    quote_request = ResearchRequest(
        company_id=SYMBOL,
        question="NVDA 现在多少钱？",
        data_mode="live",
        as_of=as_of,
    )
    quote_result = await graph.ainvoke(
        build_initial_state(quote_request),
        context=context,
    )

    quote = quote_result["results"]["quote"]
    assert quote is not None
    assert quote.symbol == SYMBOL
    assert quote.source == "longbridge"
    assert quote_result["research_status"] == "enough"
    assert provider.quote_calls == 1
    assert provider.bar_calls == 0

    provider.reset_counts()

    technical_request = ResearchRequest(
        company_id=SYMBOL,
        question="NVDA 当前走势怎么看，同时告诉我 RSI14",
        data_mode="live",
        as_of=as_of,
    )
    technical_result = await graph.ainvoke(
        build_initial_state(technical_request),
        context=context,
    )

    technical = technical_result["results"]["technical"]
    decision = technical_result["results"]["decision"]
    assert technical is not None
    assert technical.rsi14 is not None
    assert decision is not None
    assert decision.status != "blocked"
    assert technical_result["research_status"] == "enough"
    assert provider.quote_calls == 1
    assert provider.bar_calls == 1

    print("source=Longbridge")
    print("symbol=", SYMBOL)
    print("quote=", quote.price)
    print("rsi14=", technical.rsi14)
    print("market_view=", decision.market_view)
    print("Day36 Longbridge workflow verification passed.")


if __name__ == "__main__":
    asyncio.run(verify_day36_longbridge_workflow())
