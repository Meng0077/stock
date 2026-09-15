# D07：现有只读工具接入 LangChain Agent

- 开发日：D07
- 今日状态：Step 2～Step 8 已完成；仅 Step 1 学习自检待确认
- 前置基线：D06 已提交为 `0458428`；全量测试 `164 passed`
- 参考：[Week 2 计划](week2.md)、[Python 总开发计划](../stock-agent-python-development-plan.md)

## 今天结束时要得到什么

让 LangChain Agent 调用现有的两个 fixture 工具，同时保持业务实现只有一份：

```text
LangChain Agent
    → LangChain Tool adapter
    → execute_tool()
    → TOOL_REGISTRY
    → 现有 handler
    → fixture 结果
```

完成后需要能指出 LangChain 接管了模型与工具之间的循环，但白名单、参数校验、
只读限制和 fixture 语义仍由应用代码决定。

## 今天不做

- [ ] 不复制 `get_quote()` 或 `get_company_profile()` 的业务数据。
- [ ] 不修改现有 Manual Agent，D08 才做行为对照。
- [ ] 不把 FastAPI 的生产 runner 切换成 LangChain，D10 再接 API。
- [ ] 不在今天完成 `ResearchOutput` structured output，留给 D09。
- [ ] 不加入数据库、RAG、实时行情、LangSmith 或自定义 LangGraph 工作流。
- [ ] 不开启自动重试；真实模型验证只运行一次受控案例。

## 已创建文件

1. `backend/examples/langchain_smoke.py`：独立的加法工具实验，不接股票业务。
2. `backend/src/stock_agent/agents/langchain_tools.py`：现有 registry 的薄适配层。
3. `backend/src/stock_agent/agents/langchain_agent.py`：模型与 Agent 的最小组装入口。
4. `backend/tests/test_langchain_tools.py`：适配器、参数校验和白名单测试。
5. `backend/tests/test_langchain_agent.py`：Agent 输入和消息轨迹测试。
6. `backend/examples/run_day07_step7.sh`：可重复执行的真实工具往返验证命令。

## Step 0：确认 D06 基线（5 分钟）

- [x] D06 已提交，工作区在开始 D07 时干净。
- [x] 最近一次全量测试为 `164 passed`。
- [x] Manual Agent、FastAPI 和 fixture 工具保持现状。

## Step 1：只学习今天需要的 LangChain 概念（25～35 分钟）

- [ ] 理解 `create_agent(model, tools, system_prompt=...)` 创建的是循环运行时。
- [ ] 理解 `@tool` 使用函数类型注解生成参数 schema，函数 docstring 会成为工具说明。
- [ ] 理解异步工具与 Agent 使用 `await agent.ainvoke(...)`。
- [ ] 能从结果中识别 `HumanMessage → AIMessage(tool_calls) → ToolMessage → AIMessage(final)`。
可以通过 result["messages"] 查看完整轨迹。用户输入是 HumanMessage，如果模型决定调用工具，会产生带 tool_calls 的 AIMessage；工具执行结果以 ToolMessage 返回，并通过 tool_call_id 和对应的 tool call 关联；模型拿到工具结果后再次推理，最终产生一个没有 tool_calls 的 AIMessage，这通常就是 final answer
- [ ] 知道 LangChain v1 的标准入口是 `create_agent`，今天不使用旧的 `create_react_agent`。
- [ ] 知道 DeepSeek 模型必须支持 tool calling；不要默认所有模型都支持。

学习资料：

- [LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents)
- [LangChain Tools](https://docs.langchain.com/oss/python/langchain/tools)
- [ChatDeepSeek integration](https://docs.langchain.com/oss/python/integrations/chat/deepseek)

## Step 2：安装并锁定最小依赖（15～25 分钟）

- [x] 从 PyPI 官方元数据查询当前可安装版本，没有凭记忆填写版本号。
- [x] 安装并固定 `langchain==1.4.0`、`langchain-deepseek==1.1.0`。
- [x] `langgraph==1.2.11` 作为传递依赖锁定，没有重复声明为项目直接依赖。
- [x] 未直接声明 `langchain-community`、LangSmith 或其他暂时不用的集成；`langsmith==0.12.4` 是 `langchain-core` 自动解析的传递依赖，未启用 tracing。
- [x] 更新 `backend/pyproject.toml`、运行锁定文件和开发锁定文件。
- [x] `pip check` 返回 `No broken requirements found`，核心导入正常。
- [x] 运行 D06 全量测试，确认增加依赖没有破坏现有行为：`164 passed`。

Step 2 安装记录：

```text
langchain==1.4.0
langchain-deepseek==1.1.0
langchain-core==1.6.3
langchain-openai==1.6.2
langgraph==1.2.11
langsmith==0.12.4
```

## Step 3：完成独立加法工具实验（25～35 分钟）

文件：`backend/examples/langchain_smoke.py`

- [x] 定义 `add(a: int, b: int) -> int`，使用 `@tool` 和明确 docstring。
- [x] 定义 `build_smoke_agent(model) -> object`，只注册 `add`。
- [x] 定义 `run_smoke(agent, question) -> dict`，使用异步 `ainvoke`。
- [x] 模块导入时不得读取密钥、创建客户端或调用模型。
- [x] 真实运行一次 `123 + 456`，确认结果为 579，不重复请求。
- [x] 保存并观察消息类型顺序，不把完整模型对象或密钥写入文件。

Step 3 真实验证：用户已运行 `langchain_smoke.py` 并确认通过；观察到
`HumanMessage → AIMessage(tool_calls) → ToolMessage → AIMessage(final)`，
`add` 返回 579。未再次运行模型。

产出：一个与股票业务无关、可以明确观察 tool loop 的最小实验。

## Step 4：为现有 registry 编写薄 Tool adapter（35～45 分钟）

文件：`backend/src/stock_agent/agents/langchain_tools.py`

- [x] 用 `@tool("get_quote", args_schema=CompanyToolParams)` 定义异步报价 adapter。
- [x] 用 `@tool("get_company_profile", args_schema=CompanyToolParams)` 定义异步公司资料 adapter。
- [x] adapter 只能调用 `execute_tool(tool_name, arguments)`，不能直接调用 handler。
- [x] adapter 不复制 fixture 字典、公司判断、参数清理或错误消息。
- [x] 定义 `build_langchain_tools() -> list`，只返回白名单中的两个工具。
- [x] 工具名称保持 `get_quote`、`get_company_profile`，避免模型和 registry 名称漂移。
- [x] 工具说明明确只读、fixture、仅支持 NVDA、不是实时行情。

预期调用链：

```text
get_quote_tool.ainvoke({"company_id": " NVDA "})
    → execute_tool("get_quote", {"company_id": " NVDA "})
    → CompanyToolParams
    → TOOL_REGISTRY["get_quote"]["handler"]
```

## Step 5：离线验证 adapter 与白名单（35～45 分钟）

文件：`backend/tests/test_langchain_tools.py`

- [x] 工具列表恰好包含 `get_quote`、`get_company_profile`。
- [x] 两个工具的参数 schema 来自 `CompanyToolParams`，拒绝额外字段。
- [x] 合法 NVDA 调用结果与直接调用 `execute_tool()` 完全一致。
- [x] `"  NVDA  "` 经现有参数模型清理后可以执行。
- [x] 空 company_id 在调用 handler 前被拒绝。
- [x] AAPL 参数结构合法，但由现有业务规则拒绝。
- [x] 未知工具不在 LangChain 工具列表中，调用 registry 仍会被拒绝。
- [x] 测试全部离线，不创建 ChatDeepSeek，不访问网络。

Step 5 测试结果：`16 passed`。

## Step 6：组装最小股票 LangChain Agent（35～45 分钟）

文件：`backend/src/stock_agent/agents/langchain_agent.py`

- [x] 定义 `build_agent_input(request) -> dict`，包含 company_id、question、data_mode、as_of。
- [x] 定义 `build_langchain_agent(model, tools) -> object`，调用 `create_agent`。
- [x] system prompt 要求公司资料和报价必须使用工具，并声明 fixture 语义。
- [x] 定义 `invoke_langchain_agent(agent, request) -> dict`，只负责 `ainvoke` 并返回 state。
- [x] Agent 只接收 `build_langchain_tools()` 生成工具的无重复子集；按任务最小授权。
- [x] 不在这里复制 Manual Agent 的 `while`、`continue` 或工具分发代码。
- [x] 暂不转换为 `AgentRunResult`，结构化输出和 API 接入留给 D09/D10。

## Step 7：验证一次真实工具往返（20～30 分钟）

- [x] 使用当前 DeepSeek 配置前先确认模型支持 tool calling。
- [x] `ChatDeepSeek` 设置 `temperature=0`、有限 timeout、`max_retries=0`。
- [x] 只运行一次“查询 NVDA 教学模拟报价”的受控请求。
- [x] 确认轨迹包含一次模型工具请求、对应 ToolMessage 和最终 AIMessage。
- [x] 确认 ToolMessage 数据来自现有 fixture，并明确不是实时行情。
- [x] 记录模型名、消息类型顺序、工具名、参数、终态和可获得的 token 用量。
- [x] 失败时如实记录固定原因，不循环重试或临时放宽白名单。

Step 7 真实验证记录（2026-09-15）：

- 项目内复现命令：`./backend/examples/run_day07_step7.sh`。再次运行会产生新的
  模型请求并消耗 token，不属于上面记录的首次验证。

- 官方能力确认：[DeepSeek 模型功能表](https://api-docs.deepseek.com/quick_start/pricing/)
  显示 `deepseek-v4-flash` 旧别名仍可用，由服务端路由到 DeepSeek V4.1
  Flash，并支持 Tool Calls。
- 运行配置：`temperature=0`、模型超时 30 秒、`max_retries=0`、
  `max_tokens=500`、关闭 thinking。
- 最小授权：本次只向 Agent 提供 `get_quote`。
- 工具请求：`get_quote({"company_id": "NVDA"})`。
- 消息顺序：`HumanMessage → AIMessage(tool_calls) → ToolMessage → AIMessage(final)`。
- fixture 结果：NVDA、100 USD、`data_mode=fixture`、来源为本地教学模拟数据；
  最终回答正确声明不是实时行情。
- token 用量：input 1137、output 333、total 1470。
- 终态：passed；没有自动重试，也没有放宽工具白名单。

## Step 8：回归与讲解（20～30 分钟）

- [x] 运行新增 LangChain 测试。
- [x] 运行全量 pytest，记录通过数。
- [x] 确认 Manual Agent CLI 预览和 D06 FastAPI 导入仍正常。
- [x] 填写本文档的实际执行记录、文件列表、版本和限制。
- [x] 能指出 Manual Agent 中哪段 tool loop 被 LangChain runtime 接管。
在 Manual Agent 里，我自己实现了 model-tool-model loop，包括检查 tool_calls、分发工具、构造 ToolMessage、把工具结果追加回消息历史并继续下一轮模型调用。迁移到 LangChain 后，这部分 orchestration 由 create_agent 和 LangGraph runtime 接管。
但工具内部的业务边界没有交给 LangChain，实际执行仍然通过我自己的 execute_tool、TOOL_REGISTRY 和 handler，所以 LangChain 只负责 loop，不负责业务规则。
- [x] 能解释 LangChain 没有替代白名单、Pydantic 参数校验和业务限制。

LangChain 接管的是 Agent loop 的 orchestration，比如模型调用、tool call 分发、ToolMessage 回填和下一轮推理，但它没有替代系统自己的安全和业务边界。

工具白名单仍然由应用层显式控制，决定哪些能力可以暴露给 Agent；Pydantic schema 仍然定义工具参数的合法结构和约束，LangChain只是利用这套 schema 做解析和校验；像只允许 NVDA、只读、fixture 模式这类业务限制仍然应该由 execute_tool 或 domain layer 强制执行，而不能只依赖 prompt。

所以 LangChain 负责“怎么跑”，而我的代码仍然负责“允许做什么、参数是否合法、业务上能不能做”。

## D07 完成标准

- [x] LangChain Tool 没有复制任何 fixture 业务数据。
- [x] 两个工具都通过现有 `execute_tool()` 和 `TOOL_REGISTRY` 执行。
- [x] 参数非法时 handler 不执行，未知工具没有执行路径。
- [x] LangChain Agent 能完成至少一次真实 fixture 工具往返。
- [x] 能展示并解释 Human/AI(tool_calls)/Tool/AI(final) 消息顺序。
- [x] 测试不请求真实模型，真实验证不自动重试。
- [x] Manual Agent 和 FastAPI 行为没有被破坏。

## 实际执行记录（完成后填写）

- Step 8 完成时间：2026-09-15。
- 安装版本：`langchain==1.4.0`、`langchain-deepseek==1.1.0`、
  `langchain-core==1.6.3`、`langgraph==1.2.11`。
- 新增/修改文件：`langchain_smoke.py`、`langchain_tools.py`、
  `langchain_agent.py`、`test_langchain_tools.py`、`test_langchain_agent.py`、
  `run_day07_step7.sh`、`day07.md` 及依赖/锁定文件。
- LangChain 测试：工具 adapter 16 个、Agent 契约与离线 loop 11 个，
  合计 `27 passed`；不创建 ChatDeepSeek，不访问网络。
- 全量测试：`191 passed`；另有 1 条来自 Starlette TestClient 的 AnyIO
  弃用警告，不是本次功能失败。
- 兼容性检查：Manual Agent `--preview` 正常；FastAPI 可导入、
  `create_app()` 正常注册 `POST /api/runs`。
- 真实模型与消息轨迹：`deepseek-v4-flash`，
  `HumanMessage → AIMessage(tool_calls) → ToolMessage → AIMessage(final)`，
  `get_quote({"company_id": "NVDA"})` 成功，total tokens 1470。
- 已知限制：仅有 NVDA 本地 fixture；D09 才增加结构化输出，D10 才把
  LangChain runner 接入 FastAPI；真实模型行为仍可能随服务端版本变化。
- 遗留 TODO：仅剩 Step 1 学习自检；Step 3 加法和 Step 7 股票工具真实验证
  均已完成，不需要重复运行。
