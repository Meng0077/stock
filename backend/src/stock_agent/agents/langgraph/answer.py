from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
import json
from typing import Any

from langchain.messages import (
    HumanMessage,
    SystemMessage,
)
from langchain_core.language_models import (
    BaseChatModel,
)
from pydantic import BaseModel

from stock_agent.agents.langgraph.state import (
    ResearchState,
)

ANSWER_SYSTEM_PROMPT = """
你是只读的股票研究结果解释器。

研究、计算、数据质量检查和研究充分性判断
已经由上游确定性程序完成。

你的职责只有：
根据提供的 Research results，
把结果准确、清晰地解释给用户。

必须遵守以下规则：

1. 不得重新研究。
   不得自行补充 payload 中不存在的市场数据、
   财务数据、宏观数据或公司事实。

2. 不得修改确定性计算结果。
   包括但不限于：
   - quote price；
   - MA、RSI、ATR 等技术指标；
   - DecisionResult.status；
   - DecisionResult.market_view；
   - Macro actual、consensus、estimated_surprise；
   - MarketReaction reference_price；
   - MarketReaction return_pct；
   - observation status。

3. DecisionResult 是技术观点的唯一来源。
   如果 DecisionResult.market_view 已存在，
   不得根据其他指标重新给出不同方向。

4. DecisionResult.status == "blocked" 时，
   不得自行生成 bullish、bearish、
   neutral 或 mixed 等市场方向。

5. Market Reaction 只表示事件时间前后
   实际观察到的价格变化。
   除非 payload 中有独立因果证据，
   不得把时间上的先后关系表述成因果关系。

6. observation 状态必须严格保留：
   - usable：可以引用已有 price / return_pct；
   - pending：窗口尚未形成；
   - missing：窗口应已形成但行情缺失；
   - unavailable：当前数据或前置条件不足。

   不得把 pending、missing 或 unavailable
   补写成具体价格、收益率或 0%。

7. 对财报 Market Reaction：
   如果结果说明事件时间使用
   SEC 8-K accepted_at，
   必须明确这是 SEC 文件公开接收时间锚点，
   不能描述为已经验证的公司最早新闻稿发布时间。

8. Macro、Technical、Financial、
   Knowledge、Market Reaction
   是独立研究证据。
   不得自行创建综合评分、confidence、
   上涨概率、胜率或目标价。

9. research_status == "cannot_retry" 时，
   必须明确说明 missing_information
   对应的资料限制，
   但可以继续回答已有结果支持的部分。

10. research_status == "enough" 时，
    直接回答用户问题，
    不要额外声称“数据完整”或“研究已完成”。

11. 不要暴露内部字段名或 Workflow 实现细节，
    除非这些字段本身具有业务含义。

12. 使用用户问题所使用的语言回答。
"""

def serialize_research_value(
    value: object,
) -> object:
    """
    把 Research results 转成适合交给模型的
    JSON-compatible 数据。

    不改变业务字段和值。
    """
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")

    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: serialize_research_value(
                getattr(value, field.name)
            )
            for field in fields(value)
        }

    if isinstance(value, datetime) or isinstance(value, date):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, list) or isinstance(value, tuple):
        return [serialize_research_value(item) for item in value]

    if isinstance(value, dict):
        return {k: serialize_research_value(v) for k, v in value.items()}

    return value

def build_answer_input(
    state: ResearchState,
) -> dict[str, Any]:
    """
    构造 Answer Model 能看到的完整研究输入。

    这里只做数据投影，
    不产生新的研究结论。
    """
    plan = state["plan"]
    request = state['request']

    if plan is None:
        raise ValueError("research plan is missing")

    results = state.get("results", {})

    return {
        "request": request.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
        "results": serialize_research_value(results),
        "research_status": state.get("research_status"),
        "missing_information": list(state.get("missing_information", []))
    }

def build_answer_messages(
    state: ResearchState,
) -> list[
    SystemMessage | HumanMessage
]:
    """
    把已完成的 ResearchState
    转成 Answer Model 输入。

    Answer Model 不拥有工具，
    只能解释 payload。
    """
    payload = build_answer_input(state)
    return [
        SystemMessage(content=ANSWER_SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
    ]

async def answer_node(
    state: ResearchState,
    *,
    model: BaseChatModel,
) -> Any:
    """
    根据已完成的 ResearchState，
    生成最终自然语言回答。
    """

    messages = build_answer_messages(state)
    response = await model.ainvoke(messages)
    content = response.content

    if not isinstance(content, str):
        raise RuntimeError("answer model returned non-text content")

    answer = content.strip()
    if not answer:
        raise RuntimeError("answer model returned empty content")
    return {"output": answer}
