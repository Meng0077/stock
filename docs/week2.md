可以。按照你总计划，Week 2 就是 **D06–D10：FastAPI 薄接口 + LangChain 迁移**。周末的目标不是做出更多股票功能，而是让你第一周手写的 Agent 能通过 API 使用，并且你能清楚比较“Manual Agent 和 LangChain Agent 到底有什么区别”。

我建议你这周仍按 **每天约 4 小时**安排，而且不要先花两三天纯学框架。每天采用：

```text
30~45min  当天必要知识
2~2.5h    实现
45~60min  测试/对照
15~30min  文档和总结
```

---

# 一、Week 2 开始前，先掌握这些

不需要学完 FastAPI 和 LangChain，只需要有下面这几个概念。

### 1. FastAPI：重点只学 5 个东西

你需要知道：

```text
FastAPI
├─ 路由 @app.post()
├─ Pydantic Request / Response
├─ async def
├─ Depends 依赖注入
└─ TestClient / AsyncClient 测试
```

尤其你现在 Agent 本身就是：

```python
await model_loop(...)
```

所以 API 基本也会是：

```python
@app.post("/api/runs")
async def create_run(...):
    result = await run_agent(...)
    return result
```

FastAPI 官方也明确建议：如果你调用的是需要 `await` 的异步库，path operation 就使用 `async def`。([FastAPI][1])

推荐先看：

[FastAPI Async / Await](https://fastapi.tiangolo.com/async/?utm_source=chatgpt.com)

[FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/?utm_source=chatgpt.com)

[FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/?utm_source=chatgpt.com)

---

### 2. LangChain：重点理解 Agent Loop

你第一周已经自己写过：

```text
while:
    model()
      ↓
    tool_calls?
      ↓
    execute_tool()
      ↓
    tool result
      ↓
    model()
```

LangChain 当前推荐的 Agent API 是：

```python
from langchain.agents import create_agent
```

`create_agent` 本身就是一个基于 LangGraph 的 Agent runtime，会在：

```text
model node
   ↓
tool node
   ↓
model node
   ↓
...
```

之间循环，直到模型输出最终结果或者满足停止条件。([Docs by LangChain][2])

这一点非常重要。

**不要优先学很多旧教程里的：**

```python
AgentExecutor
create_openai_tools_agent
```

你现在项目直接学当前的：

```python
create_agent()
```

就行。

推荐：

[LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents?utm_source=chatgpt.com)

---

### 3. LangChain Tool

先理解：

```text
Python function
      ↓
Tool schema
      ↓
告诉模型：
name
description
arguments
      ↓
模型产生 ToolCall
      ↓
LangChain 执行 Python function
```

当前 LangChain Tool 可以直接由 Python function / coroutine 构成，也可以使用 `@tool`。([Docs by LangChain][3])

推荐：

[LangChain Tools](https://docs.langchain.com/oss/python/langchain/tools?utm_source=chatgpt.com)

---

### 4. LangChain Structured Output

你第一周已经自己做：

```python
ResearchOutput.model_validate_json(...)
```

Week 2 要比较：

```text
Manual Agent
→ 你自己 parse JSON + Pydantic

LangChain Agent
→ response_format=...
→ framework 处理一部分 structured output
```

当前 `create_agent()` 可以直接：

```python
agent = create_agent(
    model=model,
    tools=tools,
    response_format=ResearchOutput,
)
```

最终结果放在：

```python
result["structured_response"]
```

LangChain 会根据 provider 能力选择 native structured output 或 ToolStrategy。([Docs by LangChain][4])

推荐：

[LangChain Structured Output](https://docs.langchain.com/oss/python/langchain/structured-output?utm_source=chatgpt.com)

---

### 5. DeepSeek + LangChain

你现在既然已经切到 DeepSeek，我建议第二周直接使用官方 LangChain DeepSeek integration：

```bash
backend/.venv/bin/python -m pip install \
  -U langchain langchain-deepseek fastapi uvicorn
```

当前 LangChain 有专门的：

```python
from langchain_deepseek import ChatDeepSeek
```

并支持 tool calling、structured output、async、token usage。([Docs by LangChain][5])

例如：

```python
from langchain_deepseek import ChatDeepSeek

model = ChatDeepSeek(
    model=os.environ["MODEL_NAME"],
    api_key=os.environ["DEEPSEEK_API_KEY"],
    temperature=0,
    timeout=30,
    max_retries=0,
)
```

我建议：

```text
max_retries=0
```

因为你现在正在学习 failure semantics。

如果 LangChain 自动帮你 retry：

```text
第一次 429
↓
自动 retry
↓
成功
```

你反而看不到第一次失败到底怎么发生。

等项目稳定以后再增加 retry policy。

---

# 二、Week 2 每天总览

| Day | 核心任务                   | 当天必须理解                             | 当天产物                          |
| --- | ---------------------- | ---------------------------------- | ----------------------------- |
| D06 | FastAPI 薄入口            | HTTP → Pydantic → Agent → Response | `/api/runs`                   |
| D07 | LangChain Tool + Agent | LangChain 如何执行 tool loop           | LangChain Agent 能调用现有 fixture |
| D08 | Manual vs LangChain    | 框架究竟替你做了什么                         | 对照报告                          |
| D09 | 安全机制迁移                 | framework ≠ safety boundary        | timeout/budget/evidence/error |
| D10 | 最小完整链路                 | API → Agent → Tool → Result        | CLI/API + React 骨架            |

这与你总计划里的 D06–D10 一一对应。

---

# D06：FastAPI 薄接口

## 今天目标

**不要 LangChain。**

继续使用你现在已经验证通过的 Manual Agent。

把：

```bash
python structured_agent.py
```

变成：

```text
POST /api/runs
```

你的目标架构：

```text
HTTP Request
     ↓
FastAPI
     ↓
Pydantic ResearchRequest
     ↓
run_id
     ↓
现有 model_loop()
     ↓
ResearchOutput
     ↓
HTTP Response
```

---

## 上午前置：30～45 分钟

看清楚：

```python
@app.post(...)
async def xxx(...)
```

Pydantic Request Model：

```python
class ResearchRequest(BaseModel):
    question: str
    symbol: str
```

FastAPI 会自动进行：

```text
JSON
 ↓
Pydantic validate
 ↓
ResearchRequest
```

错误输入自动变成 HTTP 422。

---

## 建议目录

你总计划已经规划：

```text
backend/src/stock_agent/api/
```

作为 FastAPI 请求/响应层。

可以开始：

```text
stock_agent/
├─ api/
│  ├─ app.py
│  └─ schemas.py
├─ agents/
├─ tools/
└─ schemas/
```

---

## 示例

`schemas.py`：

```python
from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    question: str = Field(min_length=1)
    symbol: str = Field(min_length=1)


class RunResponse(BaseModel):
    run_id: str
    status: str
    result: dict | None = None
    error: dict | None = None
```

`app.py`：

```python
import uuid

from fastapi import FastAPI

from stock_agent.api.schemas import (
    ResearchRequest,
    RunResponse,
)


app = FastAPI()


@app.post(
    "/api/runs",
    response_model=RunResponse,
)
async def create_run(
    request: ResearchRequest,
) -> RunResponse:

    run_id = str(uuid.uuid4())

    # 这里暂时调用你 Week1 的 Manual Agent
    result = await run_manual_agent(
        question=request.question,
        symbol=request.symbol,
        run_id=run_id,
    )

    return RunResponse(
        run_id=run_id,
        status=result["status"],
        result=result,
    )
```

D06 不要搞：

```text
数据库
SSE
任务队列
WebSocket
Redis
```

全不需要。

你总计划也明确说 API 可以先同步返回完整结果。

---

## D06 必做测试

至少测试：

```text
正常请求
question 为空
symbol 为空
Agent model_error
Agent timeout
响应中不能出现 API Key
import app 不会调用模型
```

FastAPI 官方可以直接用：

```python
from fastapi.testclient import TestClient
```

来跑 pytest。([FastAPI][6])

例如：

```python
client = TestClient(app)

def test_empty_question():
    response = client.post(
        "/api/runs",
        json={
            "question": "",
            "symbol": "NVDA",
        },
    )

    assert response.status_code == 422
```

### D06 完成标准

你应该能回答：

> 为什么 HTTP validation 和 Agent validation 要分两层？

答案：

```text
HTTP 层
→ 用户请求是否合法

Agent/tool 层
→ 模型行为是否合法
```

---

# D07：第一次真正使用 LangChain Agent

这是 Week 2 最关键的开始。

## 今天目标

让：

```text
LangChain Agent
    ↓
调用你现有 get_quote
    ↓
返回 fixture
```

重点：

**不要重新实现 `get_quote()`。**

你原来的：

```text
TOOL_REGISTRY
execute_tool()
```

继续做业务实现的唯一来源。

---

## 上午先做最小 LangChain 实验

先不要放股票项目里。

写：

```python
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_deepseek import ChatDeepSeek


@tool
def add(a: int, b: int) -> int:
    """计算两个整数的和。"""
    return a + b


model = ChatDeepSeek(
    model="...",
    temperature=0,
)

agent = create_agent(
    model=model,
    tools=[add],
)

result = agent.invoke({
    "messages": [
        {
            "role": "user",
            "content": "请计算 123 + 456",
        }
    ]
})

print(result)
```

观察结果里的 messages。

重点看：

```text
HumanMessage
    ↓
AIMessage(tool_calls)
    ↓
ToolMessage
    ↓
AIMessage(final)
```

然后和你第一周自己做的：

```text
CompletionMessage
tool_calls
role=tool
tool_call_id
```

进行对应。

LangChain `create_agent` 会负责 model/tool 循环；当前官方就是这么定义 Agent runtime 的。([Docs by LangChain][2])

---

## 下午接你自己的 registry

开始可以写一个非常薄的 adapter：

```python
from langchain.tools import tool

from stock_agent.tools.registry import execute_tool


@tool
async def get_quote(company_id: str) -> dict:
    """查询公司的教学模拟报价。当前仅支持 NVDA。"""

    return await execute_tool(
        "get_quote",
        {"company_id": company_id},
    )


@tool
async def get_company_profile(
    company_id: str,
) -> dict:
    """查询公司的教学模拟资料。当前仅支持 NVDA。"""

    return await execute_tool(
        "get_company_profile",
        {"company_id": company_id},
    )
```

注意：

这里虽然有两个 wrapper，但**业务逻辑仍然只有一份**：

```text
LangChain wrapper
      ↓
execute_tool()
      ↓
TOOL_REGISTRY
      ↓
handler
```

不要写第二套：

```python
@tool
def get_quote(...):
    return {
        "price": 100
    }
```

那就变成重复业务逻辑了。

---

## LangChain Agent

```python
agent = create_agent(
    model=model,
    tools=[
        get_quote,
        get_company_profile,
    ],
    system_prompt="""
    你是教学股票研究助手。

    报价与公司资料必须通过工具获取。
    工具返回 fixture 时不能描述为实时行情。
    """,
)
```

调用 async 版本：

```python
result = await agent.ainvoke({
    "messages": [
        {
            "role": "user",
            "content": "查询 NVDA 教学模拟报价",
        }
    ]
})
```

---

## D07 最重要的思考题

你第一周：

```python
if message.tool_calls:
    execute_tool_and_return()
    continue
```

现在去哪了？

答案：

> 被 LangChain Agent runtime 接管了。

但是：

```text
工具业务规则
白名单
参数校验
数据模式
业务限制
```

**没有因此消失。**

LangChain Tools 本质依然是把明确输入/输出的 callable 暴露给模型。([Docs by LangChain][3])

---

# D08：Manual Agent vs LangChain 对照

进度：轻量 runner、四案例离线验证和人工对照报告已完成（2026-09-16）；独立 runner 自动化测试未补，脱稿复盘待自检。
当前实现不统计模型 / handler 次数，不恢复重型采集方案。执行记录见 [D08 文档](day08.md)，结论见 [对照报告](day08/report.md)。下面保留原教学说明。

今天尽量**少写新功能，多分析**。

这是整个 Week 2 面试价值最高的一天。

计划明确要求：

> 用相同固定案例比较 Manual Agent 和 LangChain Agent，记录调用次数、错误和工具顺序差异。

---

## 拿这几个案例跑

建议最少：

```text
正常：
D05-02 get_quote

错误：
D05-06 invalid arguments
D05-07 unknown tool

预算：
D05-10 repeated tools
```

然后做一张这样的表：

| 对比项            | Manual                    | LangChain            |
| -------------- | ------------------------- | -------------------- |
| 模型调用           | 自己 `client.create()`      | framework model node |
| tool call 解析   | 自己读取 `message.tool_calls` | framework            |
| ToolMessage 回填 | 自己 append                 | framework            |
| tool loop      | 自己 `while`                | framework            |
| 工具业务逻辑         | Registry                  | 同一个 Registry         |
| 参数校验           | 自己控制                      | LangChain + 应用层      |
| evidence 校验    | 自己实现                      | 仍由应用实现               |
| budget         | 自己实现                      | 仍应显式控制               |
| timeout        | 自己实现                      | 应用仍需控制               |
| final schema   | Pydantic parse            | structured output    |

---

## 建议真正读一次 LangChain Agent state

不要只看：

```python
result["structured_response"]
```

把：

```python
for message in result["messages"]:
    print(
        type(message).__name__,
        message,
    )
```

打印出来。

你要真正看到：

```text
HumanMessage
AIMessage
ToolMessage
AIMessage
```

这一天的价值就在这里。

---

## D08 完成标准

你必须能脱稿回答：

> LangChain 到底替代了我第一周哪部分代码？

正确答案应该类似：

> 它主要替代了模型与工具之间的 orchestration，包括消息类型、tool-call dispatch、ToolMessage 回填和 Agent loop；但工具白名单、业务校验、证据验证、超时、预算和领域规则仍然属于应用层。

---

# D09：结构化输出 + 安全边界

这一天是 Week 2 技术含量最高的一天。

## 第一部分：ResearchOutput

你现在手动：

```python
content = message.content

result = ResearchOutput.model_validate_json(
    content
)
```

LangChain 可以：

```python
agent = create_agent(
    model=model,
    tools=tools,
    response_format=ResearchOutput,
)
```

最终：

```python
result = await agent.ainvoke(...)

research_output = result[
    "structured_response"
]
```

当前 LangChain 对 structured output 提供：

```text
ProviderStrategy
ToolStrategy
```

如果 provider 原生支持，就可以走 provider strategy；否则可以通过 tool calling 得到结构化输出。([Docs by LangChain][4])

---

## 但不要删除你的 evidence validation

这点极其重要。

LangChain可以保证：

```text
{
    status: str,
    facts: list,
    ...
}
```

结构合法。

它不能保证：

```text
facts[0]：
“NVDA = 100 USD”

真的被 E1 支持
```

所以仍然：

```python
output = result["structured_response"]

validate_evidence(
    output,
    allowed_ids,
    expected_data_mode,
)
```

也就是说：

```text
LangChain structured output
         ↓
Pydantic structure OK
         ↓
你的 validate_evidence()
         ↓
domain semantics OK
```

---

# D09 第二部分：预算

不要因为：

```python
create_agent()
```

已经有 loop，就认为 budget 不需要了。

你还是需要定义：

```text
模型最多几轮
工具最多几次
任务总时间
单工具时间
```

第一周你已经知道为什么。

第二周只是研究：

> 如何把这些约束放到 framework Agent 外面或 middleware/运行配置中。

当前 `create_agent` 本身运行在 LangGraph runtime 之上。([Docs by LangChain][2])

但是这周**不要深入 LangGraph**。

第 9 周才专门学。

这里只把它当 implementation detail。

---

# D09 第三部分：错误矩阵

你可以建立：

| 故障             | 期望                 |
| -------------- | ------------------ |
| model timeout  | `model_timeout`    |
| tool timeout   | `tool_timeout`     |
| unknown tool   | handler 不执行        |
| invalid args   | handler 不执行        |
| invalid output | 明确失败/修复            |
| fake evidence  | `invalid_evidence` |
| too many calls | `budget_exhausted` |
| cancellation   | 向上传播               |

跑通之后，比较 Manual / LangChain 的差异。

---

# D10：API + LangChain + 最小前端

今天不再深入框架。

目标就是串：

```text
React
  ↓
POST /api/runs
  ↓
FastAPI
  ↓
LangChain Agent
  ↓
Tool Registry
  ↓
fixture
  ↓
ResearchOutput
  ↓
FastAPI
  ↓
React
```

你的总计划要求 D10 达到：

> CLI / API 最小研究路径跑通，并建立 React 结果页骨架。

---

## FastAPI 最终大概这样

```python
@app.post(
    "/api/runs",
    response_model=RunResponse,
)
async def create_run(
    request: ResearchRequest,
):

    run_id = str(uuid.uuid4())

    result = await research_agent.ainvoke({
        "messages": [
            {
                "role": "user",
                "content": request.question,
            }
        ]
    })

    output = result["structured_response"]

    validate_evidence(...)

    return RunResponse(
        run_id=run_id,
        status=output.status,
        result=output.model_dump(),
    )
```

---

## React 这周真的只需要这么点

因为你的优势本来就在前端，所以不要浪费时间。

页面只需要：

```text
Input
┌─────────────────────┐
│ 查询 NVDA 教学报价    │
└─────────────────────┘
        [查询]

Result

Status: completed

Facts
- NVDA 模拟报价 100 USD
  Evidence: E1

Data Mode
fixture
```

不用：

```text
Redux
复杂状态管理
漂亮 dashboard
图表
SSE streaming
```

这些后面再做。

---

# 三、我建议你 Week 2 的目录最终变成这样

```text
backend/src/stock_agent/

├── agents/
│   ├── manual_agent.py
│   └── langchain_agent.py
│
├── llm/
│   └── config.py
│
├── tools/
│   ├── registry.py
│   └── langchain_tools.py
│
├── schemas/
│   ├── research_output.py
│   └── errors.py
│
├── api/
│   ├── app.py
│   └── schemas.py
│
└── agents/
    └── evidence_validation.py
```

注意：

```text
Manual Agent
      ↓
      ├─────────────┐
                    ↓
             TOOL_REGISTRY
                    ↑
      ├─────────────┘
LangChain Agent
```

一定不要有：

```text
manual_tools.py
langchain_tools_real_business.py
```

两套业务实现。

总计划明确要求 D06 以后主应用使用 LangChain，但 Manual Agent 保留作教学对照，且不能维护两套工具业务逻辑。

---

# 四、Week 2 不需要学什么

这一点其实比“要学什么”更重要。

这周先不要深入：

```text
LangGraph graph API
checkpointer
memory
RAG
Embedding
Vector DB
PostgreSQL
SSE
Streaming
LangSmith
MCP
multi-agent
human-in-the-loop
```

你会在后面几周陆续接触。

尤其不要因为知道：

> `create_agent` 底层使用 LangGraph

就跑去研究：

```python
StateGraph
add_node()
add_edge()
Command
checkpoint
```

计划里的 LangGraph 是 **第 9 周 D41～D45**。

Week 2 只需要知道：

> `create_agent` 的 Agent loop 底层由 graph runtime 驱动。

足够。

---

# 五、第二周最应该理解的源码/原理层级

按你的学习方式，我建议不要停留在“会调 API”。

你可以把深度控制成：

### FastAPI

需要知道：

```text
Request
↓
ASGI
↓
FastAPI routing
↓
Pydantic validation
↓
dependency
↓
path operation
↓
response serialization
```

但不用读 Starlette 源码。

### LangChain

一定要能对应：

```text
你自己的 Manual Agent       LangChain

while loop              → Agent runtime
client.create()          → model node
message.tool_calls       → AIMessage.tool_calls
execute_tool()           → tool node
role="tool"              → ToolMessage
continue                 → graph edge
ResearchOutput parse     → structured_response
```

这个对应关系比背 LangChain API 重要得多。

---

# 六、Week 2 每天的验收问题

到每天结束，你问自己一个问题：

```text
D06：
我能解释 HTTP 请求怎么进入 Agent 吗？

D07：
我能指出 LangChain 在哪里完成 tool loop 吗？

D08：
我能说清 Manual 和 LangChain 各负责什么吗？

D09：
我能解释为什么用了 LangChain 后仍需要
evidence / timeout / budget / whitelist 吗？

D10：
我能从浏览器请求一路讲到模型、工具、最终结果吗？
```

如果这五个问题都能脱稿回答，Week 2 就算真正完成。

---

## 推荐阅读顺序

不建议从头把官方文档看完。按这个顺序：

1. **D06 前**：FastAPI Async → Testing。
2. **D07 前**：LangChain Agents → Tools → DeepSeek integration。
3. **D08**：重新读 Agents，对照你自己的 `model_loop()`。
4. **D09 前**：Structured Output。
5. **D10**：不再读新框架文档，只做集成。

当前 LangChain 官方 DeepSeek integration 是 `langchain-deepseek / ChatDeepSeek`，支持 Tool Calling、Structured Output、Native Async 和 Token Usage，正好覆盖你第二周需要验证的能力。([Docs by LangChain][5])

[LangChain DeepSeek Integration](https://docs.langchain.com/oss/python/integrations/chat/deepseek?utm_source=chatgpt.com)

---

如果按照你现在的进度，我建议 **Week 2 不要再投入大量时间在 Manual Agent 上增加功能**。第一周已经把 `model → tool → result → model → structured output → validation` 这条底层链路学得比较扎实了；第二周最有价值的是拿同一套案例亲自观察：

> **“我第一周自己写的这些东西，LangChain到底替我做了哪一些，又有哪些东西框架永远不能替业务代码决定。”**

这会是你这一周最重要的学习成果。

[1]: https://fastapi.tiangolo.com/async/?utm_source=chatgpt.com "Concurrency and async / await - FastAPI"
[2]: https://docs.langchain.com/oss/python/langchain/agents?utm_source=chatgpt.com "Agents - Docs by LangChain"
[3]: https://docs.langchain.com/oss/python/langchain/tools?utm_source=chatgpt.com "Tools - Docs by LangChain"
[4]: https://docs.langchain.com/oss/python/langchain/structured-output?utm_source=chatgpt.com "Structured output - Docs by LangChain"
[5]: https://docs.langchain.com/oss/python/integrations/chat/deepseek?utm_source=chatgpt.com "ChatDeepSeek integration - Docs by LangChain"
[6]: https://fastapi.tiangolo.com/tutorial/testing/?utm_source=chatgpt.com "Testing - FastAPI"
