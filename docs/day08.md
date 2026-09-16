# D08：Manual Agent vs LangChain Agent 行为对照

- 开发日：D08。
- 今日状态：轻量 runner、四案例离线验证和对照报告已完成；独立 runner 测试未补，脱稿复盘待自检。
- 整理与复核日期：2026-09-16。
- 前置基线：D07 提交 3e50d2d，当时全量测试 191 passed；D08 复核时回归 207 passed，已包含部分 D09 增量。后续 D09 状态见 [D09 执行记录](day09.md)。
- 参考：[Week 2 计划](week2.md)、[Python 总开发计划](../stock-agent-python-development-plan.md)。
- 产出：[Manual / LangChain 对照报告](day08/report.md)。

## 当前范围：轻量 comparison runner

按最新要求，evals/run_agent_comparison.py 只做以下事情：

1. compare_case(case) 分别运行 run_manual(case)、run_langchain(case)。
2. summarize_manual、summarize_langchain 提取状态、错误、工具顺序、工具结果和消息类型。
3. 返回包含 case_id、manual、langchain 的普通字典。
4. 默认运行 D05-02/06/07/10；没有 --case 参数，结果打印到终端，报告人工填写。

不统计模型或 handler 次数，不要求自动 differences、AgentObservation / CaseComparison、自动 Markdown 报告或新增采集系统。

旧 comparison.py 和 test_agent_comparison.py 是未参与当前 runner 的重型方案骨架，不属于轻量实现的必做项，也不能算作已实现或已执行的测试。

## 文件与职责

| 文件 | 当前用途 |
| --- | --- |
| evals/run_agent_comparison.py | 四个固定案例的离线 runner 与摘要 |
| evals/basic_cases.jsonl | 复用 D05 输入和 scripted responses，不复制案例 |
| backend/src/stock_agent/agents/manual/manual_agent.py | Manual model_loop |
| backend/src/stock_agent/agents/langchain/langchain_agent.py | 创建 Agent，内部提供固定工具 |
| docs/day08/report.md | 实际结果、职责边界、差异解释与复盘 |

## Step 0：确认基线

- [x] 保留 D07 基线：提交 3e50d2d，当时 191 passed。
- [x] 复用原 Manual loop、同一个 registry 和 fixture handler。
- [x] 注明当前复核包含部分 D09 增量，不将结果冒充纯 D07 快照。

## Step 1：对照两种 loop

- [x] 报告列出模型调用、工具分发、消息回填和循环调度的对应职责。
- [x] 记录 HumanMessage → AIMessage(tool_calls) → ToolMessage → AIMessage(final)。
- [x] 说明 Manual 最终答案单独保存，消息列表差异不等于调用次数差异。
- [x] 说明框架接管编排不等于接管业务规则与安全边界。

## Step 2：固定案例与比较口径

- [x] 复用 D05-02 正常报价、D05-06 空 company_id、D05-07 未知工具、D05-10 持续请求工具。
- [x] 比较状态、错误、工具顺序、工具结果和消息类型，不强行统一内部表示。

## Step 3：读取 Manual 结果

- [x] run_manual 复用 D05 离线 runner、scripted client 和原始 model_loop。
- [x] summarize_manual 从原事件读取工具顺序、结果、终态、安全错误和消息类型。
- [x] 不为对照修改 Manual 行为。

## Step 4：运行 LangChain 并读取 state

- [x] 将同一 case 的 scripted responses 转成 AIMessage，fake model 支持 bind_tools。
- [x] Agent 内部提供固定工具，调用方只传 model，不创建真实模型客户端。
- [x] recursion_limit=6 限制重复工具案例；异常仅记录类型名。
- [x] summarize_langchain 读取实际工具顺序、结果和消息类型。

## Step 5：生成两份摘要

- [x] compare_case 返回同一案例的 manual / langchain 普通字典。
- [x] 四个固定案例均输出两份摘要。
- [x] 明确 returned 仅表示 loop 返回，不表示最终业务状态或证据校验通过。
- [x] 明确 GraphRecursionError 与 Manual budget_exhausted 的边界口径不同。

## Step 6：整理人工报告

- [x] 填写四案例终态、错误、工具顺序、结果和消息流程。
- [x] 填写 framework / application 职责边界。
- [x] 保留已有结论，补充状态层次和预算差异解释。
- [x] 清理空模板、重复表格和旧方案必做项，不虚构调用次数。

## Step 7：离线验证与测试状态

- [x] 实际运行轻量 runner，四案例均结束，无真实模型请求。
- [x] 现有 LangChain 测试验证非法参数与未知工具不会进入 handler。
- [x] 后端全量回归通过：207 passed。
- [ ] 轻量 runner 的独立自动化测试尚未补充；旧 test_agent_comparison.py 只有测试清单，不作为通过依据。

## Step 8：复盘与文档收口

- [x] D07 Step7 保存脚本语法检查通过，不再次请求真实模型。
- [x] 填写执行记录、对照结论和 D09 剩余项。
- [x] 报告补充口语化面试回答。
- [ ] 学习者自检：能否脱稿解释 LangChain 替代了哪部分 Manual 代码？
- [ ] 学习者自检：为什么仍需要 whitelist、Pydantic、evidence、timeout 和 budget？

## D08 开发与报告完成标准

- [x] 四个固定案例均产生 Manual / LangChain 两份摘要。
- [x] 使用相同 D05 案例和同一 registry，不复制业务逻辑。
- [x] 报告记录终态、错误、工具顺序、消息流程和实际差异。
- [x] 非法参数和未知工具没有 handler 执行路径，已有测试覆盖。
- [x] 重复工具案例在有限边界结束，不把递归限制当作业务预算。
- [x] 报告明确区分 framework orchestration 与 application policy。

以上表示轻量开发与报告收口完成，不表示独立 runner 测试或学习者脱稿自检已完成。

## 实际执行记录

- 整理与复核日期：2026-09-16。
- D08 验证：四个固定案例离线运行成功；未补独立 runner 自动化测试。
- 全量测试：207 passed，另有一条 Starlette / AnyIO 弃用警告。
- D07 Step7：脚本语法检查通过，未请求真实模型。
- D05-02：Manual completed；LangChain returned；双方一条成功报价结果。
- D05-06：Manual insufficient_information；LangChain returned；双方工具参数校验失败。
- D05-07：Manual insufficient_information；LangChain returned；未知工具没有执行路径。
- D05-10：Manual budget_exhausted，两条成功工具结果；LangChain GraphRecursionError，三条成功工具结果。
- LangChain 接管：模型与工具调度、工具消息回填、model → tool → model 循环。
- 应用仍负责：白名单、业务 schema、资料来源、证据校验、预算、超时和错误边界。
- 后续 D09 已完成：ToolStrategy、公共入口证据校验、模型／工具预算、超时、统一安全终态、运行事件与结果、截断保护；最新回归 226 passed，见 [D09 执行记录](day09.md)。
- D09 遗留：无 choices／非法 JSON 的 LangChain 路径专项验收，按用户要求暂不处理。本节其他结果保留 D08 复核时的记录。

运行命令：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python evals/run_agent_comparison.py
```
