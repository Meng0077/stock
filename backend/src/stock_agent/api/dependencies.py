"""D06 Step 5：FastAPI 依赖边界。

生产环境返回 run_manual_agent；测试通过 dependency_overrides 替换为离线 fake。
获取依赖时不能创建客户端、读取密钥或访问网络。
"""

from collections.abc import Awaitable, Callable
from functools import lru_cache
from pathlib import Path
from typing import cast
from uuid import UUID

from langchain.agents.structured_output import ToolStrategy
from langchain_deepseek import ChatDeepSeek
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from stock_agent.agents.langchain.langchain_agent import build_langchain_agent
from stock_agent.agents.langgraph.graph import build_research_graph
from stock_agent.agents.manual.manual_runner import run_manual_agent
from stock_agent.api.schemas import AgentRunResult
from stock_agent.api.research_event_store import ResearchEventStore
from stock_agent.llm_client import get_llm_config
from stock_agent.macro.config_factory import build_macro_snapshot_builder
from stock_agent.market.longbridge.config_factory import build_longbridge_market_provider
from stock_agent.schemas.research import ResearchRequest
from stock_agent.schemas.research_output import ResearchOutput

ROOT = Path(__file__).resolve().parents[4]
MODEL_TIMEOUT_SECONDS = 30

AgentRunner = Callable[[ResearchRequest, UUID], Awaitable[AgentRunResult]]


def get_agent_runner() -> AgentRunner:
    """无输入；返回异步 Agent runner 函数；本函数本身不得执行 Agent。"""
    # D06-Step-5.1：只返回函数对象，不在依赖解析阶段执行 Agent。
    return run_manual_agent


@lru_cache
def get_chat_model():
    """
    创建项目共享的 Chat Model。

    Target Resolver 和 Agent
    使用同一套模型配置，
    避免各自重复创建客户端。
    """

    config = get_llm_config(ROOT / "backend" / ".env")
    if config is None:
        raise RuntimeError("LLM configuration is incomplete")

    return ChatDeepSeek(
        model=config.model,
        api_key=cast(SecretStr, config.api_key),
        temperature=0,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=0,
        extra_body={"thinking": {"type": "disabled"}},
    )


@lru_cache
def get_langchain_agent():
    return build_langchain_agent(
        model=get_chat_model(),
        response_format=ToolStrategy(ResearchOutput),
    )


@lru_cache
def get_macro_snapshot_builder():
    """首次调用宏观 Tool 时才创建真实 Provider。"""

    return build_macro_snapshot_builder()


def get_macro_builder_factory():
    """向请求上下文注入延迟创建 Builder 的函数。"""

    return get_macro_snapshot_builder


@lru_cache
def get_market_data_provider():
    """首次调用行情 Tool 时才创建真实长桥 Provider。"""

    return build_longbridge_market_provider()


def get_market_provider_factory():
    """向请求上下文注入延迟创建行情 Provider 的函数。"""

    return get_market_data_provider


@lru_cache
def get_research_graph():
    checkpointer = InMemorySaver()
    return build_research_graph(
        model=get_chat_model(),
        checkpointer=checkpointer,
    )


@lru_cache
def get_research_event_store() -> ResearchEventStore:
    """
    当前进程共享的 Research Event Store。

    start / resume / continue 与 SSE
    必须看到同一份 event buffer。
    """
    return ResearchEventStore()
