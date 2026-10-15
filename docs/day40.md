# Day40：React 研究界面与工作流交互

## 当前结论

Day40 调整后的当前范围已经完成。

真实研究命令、`thread_id` 绑定、SSE 阶段进度、Answer 增量展示、终态处理、标的 clarification/resume、Cancel API、取消按钮和失败回退已经进入前端主流程并完成验收。

Continue UI、页面恢复、`target_resolution` 详情卡片，以及 Quote、Technical、Decision、财报、Macro、Market Reaction 的结构化展示暂不实现，移出 Day40 验收范围，后续再处理。

## 完成度矩阵

| Day40 范围 | 状态 | 当前说明 |
| --- | --- | --- |
| 自然语言研究请求 | 已完成 | `POST /api/research` 返回 `thread_id`，页面随后订阅 SSE |
| 工作流阶段展示 | 已完成 | 展示 Target Resolution、Planning、Research、Checking、Answering 阶段 |
| Answer 增量展示 | 已完成 | 使用 `SSETaskQueue`、`TextBuffer` 和 `TextTask` 顺序展示文本 |
| SSE 终态 | 已完成 | 支持 `completed / failed / cancelled`，失败使用公开错误文本 |
| 标的 clarification 表单 | 已完成 | 展示候选 ticker 与手动输入；有效答案为空时不能提交 |
| Resume | 已完成 | 使用原 `thread_id` 和非空 `answer` 恢复，不替换原研究问题 |
| Cancel API 与按钮 | 已完成 | 已覆盖请求参数、`cancelling`、SSE `cancelled`、失败回退与 Toast、按钮触发、禁用状态和竞态 |
| Continue UI | 后置 | 不属于 Day40 当前验收范围，后续处理 |
| `target_resolution` 卡片 | 后置 | 不属于 Day40 当前验收范围，后续处理 |
| Quote / Technical / Decision / 财报 / Macro / Market Reaction 结构化展示 | 后置 | 不属于 Day40 当前验收范围，等待后续公开结果契约 |
| 页面恢复 | 后置 | 不属于 Day40 当前验收范围，后续处理 |

## 当前前端流程

```text
自然语言问题
  -> POST /api/research
  -> accepted + thread_id
  -> GET /api/research/{thread_id}/events
  -> workflow_started / stage_changed / answer_delta
  -> needs_input 时展示 clarification
  -> POST /api/research/resume
  -> 同一 SSE 连接继续接收事件
  -> completed / failed / cancelled
```

Clarification 只提交非空 ticker 列表：

```json
{
  "thread_id": "原 thread_id",
  "answer": ["GOOGL"]
}
```

前端会先对输入执行 `trim` 并过滤空字符串。没有有效答案时确认按钮不可用；后端 `ResearchResumeInput.answer` 同时保留 `min_length=1` 校验。

## 本次检查发现的问题

以下项目涉及业务行为，本次按约束只记录、不修改：

1. **历史轮次仍可显示 clarification 表单。** 页面当前没有限制只有最新一轮可以提交澄清；若后续允许在等待输入时开始新问题，需要明确历史轮次行为。
2. **结构化结果尚无前端契约。** 当前 `completed.data.result` 仍按字符串消费；相关卡片已经移出 Day40 范围，后续实现时需要先定义公开结果契约。
3. **Toast 文件有 Fast Refresh warning。** `toast.tsx` 同时导出 Hook 与组件；不影响类型检查和测试，但 lint 会提示 `react/only-export-components`。

## 验收结果

本次检查后的本地结果：

- 前端类型检查：通过；
- 前端测试：`96 passed`；
- 后端 Research API / SSE / Task 专项：`55 passed`；
- 前端生产构建：通过；
- Oxlint：无 error，保留 1 条 `toast.tsx` Fast Refresh warning；
- `git diff --check`：通过。

## Day40 后置项

Day40 当前范围没有剩余验收项。Continue UI、页面恢复、`target_resolution` 详情卡片和六类结构化研究结果展示不属于本日范围，后续再处理。
