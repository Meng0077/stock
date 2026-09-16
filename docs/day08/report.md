# D08 Manual Agent vs LangChain Agent 对照报告

- 状态：轻量方案对照报告已整理完成。
- 整理与复核日期：2026-09-16。
- 数据来源：evals/run_agent_comparison.py，复用 D05-02/06/07/10 和同一个 TOOL_REGISTRY。
- 验证方式：scripted/fake model 离线运行，不读取真实模型配置、不访问网络。

## 比较口径

同一个 case 分别执行 Manual 和 LangChain，记录终态、错误、工具顺序、工具结果和消息类型。
按简化后的计划，不统计模型调用次数或 handler 次数，不要求自动生成报告。

本次复核使用当前工作区代码，其中已经包含部分 D09 增量（工具证据 ID、业务错误和工具超时 middleware），不是纯 D07 快照。
D08 runner 没有配置 ResearchOutput，也没有执行最终证据校验；这些能力不能仅凭本报告判定完成。

以下表格保留 D08 复核时的行为快照，不代表后续 D09 的最新安全边界；最新实现与验收见 [D09 执行记录](../day09.md)。

## 固定案例终态

| 案例 | 场景 | Manual 终态 / 错误 | LangChain 终态 / 错误 | 主要差异 |
| --- | --- | --- | --- | --- |
| D05-02 | 正常报价 | completed / 无 | returned / 无 | 都成功查询报价；returned 仅表示 loop 返回，不代表输出通过业务校验 |
| D05-06 | 空 company_id | insufficient_information / 无运行错误 | returned / 无运行错误 | 两边都有工具错误消息；Manual 状态来自模型输出，LangChain runner 不解析最终业务状态 |
| D05-07 | 未知工具 | insufficient_information / 无运行错误 | returned / 无运行错误 | 未知工具都没有执行路径；事件和工具名的表示不同 |
| D05-10 | 持续请求工具 | budget_exhausted / budget_exhausted | error / GraphRecursionError | 都在各自边界停止，但业务预算不等于递归步数限制 |

工具错误不等于整个 run 失败：错误消息交给模型后，模型仍可返回“信息不足”。
returned、completed、insufficient_information 不是同一层面的状态，不能强行对齐。

## 工具顺序和结果

| 案例 | Manual 工具顺序 | Manual 工具结果 | LangChain 工具顺序 | LangChain 工具结果 |
| --- | --- | --- | --- | --- |
| D05-02 | get_quote | tool_succeeded | get_quote | success |
| D05-06 | get_quote | tool_failed | get_quote | error |
| D05-07 | unknown_tool | tool_failed | delete_file | error |
| D05-10 | get_quote → get_quote | 两条成功结果 | get_quote → get_quote → get_quote | 三条成功结果 |

正常调用的语义一致，结果表示不同。未知工具案例中，Manual 把事件工具名归为 unknown_tool，LangChain 保留请求的 delete_file；不代表 Manual 请求了另一个工具。

重复调用案例中，LangChain 多产生一条成功工具结果。原因是 runner 配置 recursion_limit=6，而 Manual 使用自己的轮数和工具预算；两种限制的计数口径不同，不能把“多一条工具结果”理解成框架默认多执行一轮模型调用。

## 消息流程

| 案例 | Manual 记录的消息类型 | LangChain state 消息类型 |
| --- | --- | --- |
| D05-02 | system → user → assistant → tool | HumanMessage → AIMessage → ToolMessage → AIMessage |
| D05-06 | system → user → assistant → tool | HumanMessage → AIMessage → ToolMessage → AIMessage |
| D05-07 | system → user → assistant → tool | HumanMessage → AIMessage → ToolMessage → AIMessage |
| D05-10 | system → user → assistant → tool → assistant → tool | HumanMessage → AIMessage → ToolMessage → AIMessage → ToolMessage → AIMessage → ToolMessage |

这里比较的是 runner 实际读取的消息容器，不是完整的模型请求次数。
Manual 的最终答案单独保存在 final_output，没有追加到这份 run_messages；LangChain 将最终 AIMessage 保留在 state 中。Manual 表格没有最后一条 assistant，不代表模型没有生成最终答案。
LangChain 的 system prompt 在模型调用时加入，也不意味着缺少系统指令。

## 职责边界

| 对比项 | Manual Agent | LangChain Agent | 责任边界 |
| --- | --- | --- | --- |
| 模型调用 | 自己调用 client.create | framework model node 调用模型 | 框架负责调度，应用配置模型与请求限制 |
| tool call 分发 | 自己读取 tool_calls 并执行 | framework tool node 分发到 adapter | 应用只提供授权工具 |
| 工具消息回填 | append role=tool 字典 | framework 写入 ToolMessage | 框架处理协议，应用提供工具结果 |
| tool loop | while / continue / return | LangChain/LangGraph runtime | 框架接管编排，不自动迁移业务策略 |
| 工具白名单 | TOOL_REGISTRY | 固定 adapters → 同一 TOOL_REGISTRY | 应用 |
| 参数校验 | CompanyToolParams | LangChain 参数 schema + registry 校验 | 应用定义 schema，框架负责工具输入适配 |
| 公司与 fixture 限制 | 原工具 handler | 相同 handler | 应用业务逻辑 |
| 预期工具错误 | execute_tool_and_return 捕获并回填错误 | 默认工具节点 + 应用 middleware | 应用决定哪些异常可交给模型，非预期异常不应一律吞掉 |
| evidence 校验 | 成功工具登记 ID，最终 validate_evidence | D08 快照：adapters 附加 ID，脚本校验；后续 D09 公共入口已接入 | 应用；ToolStrategy 不验证引用来源 |
| budget | 显式轮数、工具次数限制 | D08 快照：recursion_limit=6；后续 D09 已迁移模型／工具业务预算 | 应用 |
| timeout / cancel | 工具与模型限时，取消传播 | D08 快照：单工具限时和取消传播；后续 D09 已补任务总超时与模型超时终态 | 应用 |
| 最终 schema | Pydantic 解析 JSON | D08 runner 返回原始 state；D09 验证脚本另用 ToolStrategy | 应用定义输出模型，框架辅助生成和校验 |

## 我的结论

1. 正常工具调用：Manual 与 LangChain 使用相同工具和业务逻辑；框架没有替我们实现报价查询。
2. 工具失败：两边都能向模型提供错误消息。Manual 使用 tool_failed 事件和错误 JSON，LangChain 使用 error ToolMessage；工具失败不强制决定最终研究状态。
3. 未知工具：两边都没有执行路径，差异主要在工具名和错误记录的表示。
4. Tool loop：LangChain 主要替代 model → tool → model 的编排，包括分发、工具消息回填和循环调度。
5. Round budget：Manual 的轮数和工具次数限制不会因为使用 create_agent 自动保留，必须显式迁移。
6. Manual 更容易直接看到每轮判断和事件写入；LangChain 减少了循环与消息协议样板代码，但排查业务问题仍需要读 state 和 middleware。

面试口语表达：

> 我先自己写了 Manual Agent，再用同一批固定案例对照 LangChain。它主要帮我接管模型与工具之间的循环、工具分发和消息回填，但工具本身仍然复用我的 registry。白名单、参数规则、证据校验、预算和超时不会因为用了框架就自动完成。比如重复工具案例，两边都会停止，但停止边界的计数方式不同，所以我不能拿递归限制直接当业务预算。

## 验证与后续

- 四个固定案例：本次复核均产生 Manual / LangChain 两份摘要，结果如上。
- 后端回归：207 passed，另有一条 Starlette / AnyIO 弃用警告。
- D07 Step7 保存脚本：语法检查通过，未调用真实模型。
- D08 独立 runner 自动化测试：尚未补充；test_agent_comparison.py 仍为旧方案测试清单，不计作已执行测试。
- 后续 D09：核心整合和截断保护已完成，最新回归 226 passed；无 choices／非法 JSON 的 LangChain 路径专项验收按用户要求遗留，见 [D09 执行记录](../day09.md)。
