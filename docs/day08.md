# D08：Manual Agent vs LangChain Agent 行为对照

- 开发日：D08
- 今日状态：TODO、代码骨架和报告模板已建立；从 Step 1 开始
- 前置基线：D07 已提交为 `3e50d2d`；全量测试 `191 passed`
- 参考：[Week 2 计划](week2.md)、[Python 总开发计划](../stock-agent-python-development-plan.md)

## 今天结束时要得到什么

用相同的 D05 固定案例分别驱动 Manual Agent 和 LangChain Agent，按共同口径记录：

```text
同一 D05 case + scripted model decisions + 同一 TOOL_REGISTRY
                    │
          ┌─────────┴─────────┐
          ↓                   ↓
    Manual model_loop    LangChain create_agent
          │                   │
          └─────────┬─────────┘
                    ↓
       调用次数 / 错误 / 工具顺序 / 消息轨迹
```

产出一份基于实际行为的对照报告，并能解释框架接管了什么、哪些安全与业务责任
仍属于应用代码。

## 今天不做

- [ ] 不修改 Manual Agent 的现有行为。
- [ ] 不复制 D05 案例、fixture 或工具 handler。
- [ ] 不请求真实模型；对照使用 scripted/fake model，保证结果稳定可复现。
- [ ] 不在 D08 给 LangChain 补 timeout、budget、evidence、结构化输出或安全错误映射；这些属于 D09。
- [ ] 不把 LangChain Agent 接入 FastAPI；这属于 D10。
- [ ] 不用代码行数作为主要比较指标，只比较可观察行为和职责边界。

## 已创建文件

1. `backend/src/stock_agent/agents/comparison.py`：共同观察模型与归一化函数。
2. `evals/run_agent_comparison.py`：四个固定案例的离线对照 runner。
3. `backend/tests/test_agent_comparison.py`：选择、归一化、对照与安全边界测试。
4. `docs/day08/report.md`：最终对照报告模板。

## Step 0：确认 D07 基线（5～10 分钟）

- [x] D07 提交为 `3e50d2d`，开始 D08 时工作区干净。
- [x] D07 全量测试为 `191 passed`。
- [x] Manual Agent、LangChain Agent 和两个 fixture 工具均保留现状。

## Step 1：读懂两种 loop 的对应关系（25～35 分钟）

- [ ] 阅读 `manual_agent.model_loop()`，找到模型请求、`tool_calls` 判断、
  `execute_tool_and_return()`、`continue` 和最终停止的位置。
- [ ] 阅读 LangChain state，能识别
  `HumanMessage → AIMessage(tool_calls) → ToolMessage → AIMessage(final)`。
- [ ] 写出以下对应关系：

```text
Manual while loop          → LangChain/LangGraph Agent runtime
client.create()            → model node
message.tool_calls         → AIMessage.tool_calls
execute_tool_and_return()  → tool node + adapter
role="tool" 字典           → ToolMessage
continue                   → graph edge 回到 model node
```

- [ ] 理解“框架接管 orchestration”不等于“框架接管业务规则和安全边界”。

## Step 2：固定公平比较契约（25～35 分钟）

文件：`backend/src/stock_agent/agents/comparison.py`

- [ ] 复用 `evals/basic_cases.jsonl`，只选择：
  - `D05-02`：正常 `get_quote`。
  - `D05-06`：空 `company_id`。
  - `D05-07`：未知工具。
  - `D05-10`：持续请求工具。
- [ ] 实现 `select_comparison_cases(cases, case_ids) -> list[dict]`，缺失、重复或顺序漂移时拒绝。
- [ ] 使用 `AgentObservation` 作为共同口径：终态、模型调用次数、工具请求与结果、
  handler 次数、消息类型和异常类型。
- [ ] 明确不要求两边内部事件结构一致，也不比较代码行数。

## Step 3：归一化 Manual Agent 记录（30～40 分钟）

文件：`comparison.py`、`evals/run_agent_comparison.py`

- [ ] 实现 `run_manual_case(case) -> AgentObservation`，复用 D05
  `ScriptedClient`、runner 和原始 `model_loop()`。
- [ ] 实现 `observe_manual_record(record) -> AgentObservation`。
- [ ] 从现有事件读取工具请求/成功/失败顺序，不重新解释业务结果。
- [ ] 统计模型调用和 handler 执行次数；每个案例结束后恢复 handler。
- [ ] 不改 Manual Agent 以迎合 LangChain 的状态格式。

## Step 4：离线驱动 LangChain Agent（40～55 分钟）

文件：`evals/run_agent_comparison.py`、`comparison.py`

- [ ] 把同一案例的 `scripted_responses` 转成 LangChain `AIMessage` 序列。
- [ ] fake model 实现 `bind_tools()`，记录模型节点实际调用次数。
- [ ] Agent 仍只使用 `build_langchain_tools()` 的最小工具子集。
- [ ] 用 spy 统计真正进入 registry handler 的次数，结束后必须恢复。
- [ ] 为重复工具案例设置有限 `recursion_limit`，防止离线测试无限循环。
- [ ] 实现 `observe_langchain_state(...) -> AgentObservation`；如果框架抛异常，
  只记录异常类型，不在 D08 映射成 D09 的公开错误。

## Step 5：运行四个固定案例并生成差异（35～45 分钟）

- [ ] 实现 `run_comparison(cases) -> list[CaseComparison]`。
- [ ] 实现 `compare_case(manual, langchain) -> CaseComparison`，要求相同 case_id。
- [ ] 对每个案例记录模型调用次数、工具请求顺序、工具结果、handler 次数、
  消息类型、终态和异常。
- [ ] 区分“行为一致”“状态表示不同”“安全机制尚未迁移”三类结论。
- [ ] 不把预期差异当作测试失败，也不为了表格相同而修改 Agent。

## Step 6：生成并填写对照报告（30～40 分钟）

文件：`docs/day08/report.md`

- [ ] 实现 `render_report(comparisons) -> str`，只写脱敏共同指标。
- [ ] 实现 runner CLI，默认离线并安全写入报告。
- [ ] 填写四案例表格，不保留 `TODO`。
- [ ] 填写职责边界表，不声称 LangChain 自动提供了 D09 安全机制。
- [ ] 写出自己的结论：框架减少了哪些编排代码、应用仍负责什么。

运行命令：

```bash
PYTHONPATH=backend/src \
backend/.venv/bin/python \
evals/run_agent_comparison.py
```

## Step 7：离线测试（35～45 分钟）

文件：`backend/tests/test_agent_comparison.py`

- [ ] 案例选择严格且顺序稳定。
- [ ] 两种 observation 只包含共同、安全、可序列化字段。
- [ ] 正常报价的工具名、参数、fixture 和 handler 次数可核对。
- [ ] 非法参数与未知工具不会进入 handler。
- [ ] 重复工具案例会在有限边界内结束，不挂住测试。
- [ ] 每个案例结束后 registry handler 恢复。
- [ ] 测试导入和执行均不读取密钥、不创建真实模型、不访问网络。

## Step 8：回归、复盘与面试表达（25～35 分钟）

- [ ] 运行 D08 新增测试。
- [ ] 运行全量 pytest 并记录结果。
- [ ] 确认 D07 Step7 脚本仍能通过语法检查，但不再次请求模型。
- [ ] 填写本文档实际执行记录、差异摘要和遗留 D09 项目。
- [ ] 能脱稿回答：LangChain 替代了 Manual Agent 的哪部分代码？
- [ ] 能脱稿回答：为什么用了 LangChain 后仍需要 whitelist、Pydantic、
  timeout、budget、evidence 和安全错误映射？

## D08 完成标准

- [ ] 四个固定案例都产生 Manual/LangChain 两条观察记录。
- [ ] 对照数据来自同一 D05 案例和同一 registry，没有复制业务逻辑。
- [ ] 报告记录调用次数、错误、工具顺序和消息类型差异。
- [ ] 未知工具和非法参数没有执行 handler。
- [ ] 重复工具案例有有限测试边界，不会无限运行。
- [ ] 能准确区分 framework orchestration 与 application policy。

## 实际执行记录（完成后填写）

- 完成时间：
- D08 测试：
- 全量测试：
- 四案例结果：
- 主要差异：
- LangChain 接管：
- 应用仍负责：
- D09 遗留：
