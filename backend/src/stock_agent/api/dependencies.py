"""D06 Step 5：FastAPI 依赖边界。

生产环境返回 run_manual_agent；测试通过 dependency_overrides 替换为离线 fake。
获取依赖时不能创建客户端、读取密钥或访问网络。
"""

from functools import lru_cache
from collections.abc import Awaitable, Callable
from uuid import UUID

from stock_agent.schemas.research_output import ResearchOutput
from stock_agent.agents.manual.manual_runner import run_manual_agent
from stock_agent.api.schemas import AgentRunResult
from stock_agent.schemas.research import ResearchRequest

from pathlib import Path

from langchain_deepseek import ChatDeepSeek

from stock_agent.agents.langchain.langchain_agent import (
    build_langchain_agent,
)
from stock_agent.llm_client import get_llm_config
from stock_agent.macro.config_factory import build_macro_snapshot_builder

from langchain.agents.structured_output import ToolStrategy



ROOT = Path(__file__).resolve().parents[4]
MODEL_TIMEOUT_SECONDS = 30

AgentRunner = Callable[[ResearchRequest, UUID], Awaitable[AgentRunResult]]


def get_agent_runner() -> AgentRunner:
    """无输入；返回异步 Agent runner 函数；本函数本身不得执行 Agent。"""
    # D06-Step-5.1：只返回函数对象，不在依赖解析阶段执行 Agent。
    return run_manual_agent

@lru_cache
def get_langchain_agent():
    config = get_llm_config(
        ROOT / "backend" / ".env"
    )
    
    model = ChatDeepSeek(
        model=config.model,
        api_key=config.api_key,
        temperature=0,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=0,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return build_langchain_agent(model=model, response_format=ToolStrategy(ResearchOutput))


@lru_cache
def get_macro_snapshot_builder():
    """首次调用宏观 Tool 时才创建真实 Provider。"""

    return build_macro_snapshot_builder()


def get_macro_builder_factory():
    """向请求上下文注入延迟创建 Builder 的函数。"""

    return get_macro_snapshot_builder
