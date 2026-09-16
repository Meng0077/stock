"""D06 Step 5：FastAPI 依赖边界。

生产环境返回 run_manual_agent；测试通过 dependency_overrides 替换为离线 fake。
获取依赖时不能创建客户端、读取密钥或访问网络。
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from stock_agent.agents.manual.manual_runner import run_manual_agent
from stock_agent.api.schemas import AgentRunResult
from stock_agent.schemas.research import ResearchRequest


AgentRunner = Callable[[ResearchRequest, UUID], Awaitable[AgentRunResult]]


def get_agent_runner() -> AgentRunner:
    """无输入；返回异步 Agent runner 函数；本函数本身不得执行 Agent。"""
    # D06-Step-5.1：只返回函数对象，不在依赖解析阶段执行 Agent。
    return run_manual_agent
