# Day38：Target Resolver 的 Graph 接入与恢复

## 完成结论

Day38 的核心工作流已完成：Target Resolver 位于 Planner 之前，标的不唯一或无法确定时通过 LangGraph `interrupt()` 暂停，用户补充后使用同一 `thread_id` 恢复并重新验证标的。

```text
ResearchInput.message
  ↓
resolve_target
  ├─ resolved → planner
  ├─ absent → planner
  └─ multiple / ambiguous / unresolved
       ↓
    clarify_target → interrupt
       ↓ resume(answer)
    resolve_target 重新验证
       ↓
    planner → research → checker → answer
```

## Graph 边界

`resolve_target_node` 处理三类输入：

- 自然语言 API 创建的 `company_id=None` 请求会解析原始问题；
- 已归一化的内部 `ResearchRequest` 保持向后兼容，直接规范化 ticker，不重复调用 Resolver 或模型；
- 恢复时只解析用户最新补充的标的表达，不会绕过 Registry 验证。

`absent` 不会立即失败。它先进入 Planner：

- 纯宏观计划可以以 `company_id=None` 进入 Research；
- 报价、技术分析、决策、公司资料、财务数据和 Market Reaction 等需要证券的计划会转入澄清节点；
- Research 节点仍保留检查，防止缺少 target 的证券计划误执行。

## API 契约

`POST /api/research` 为每次请求创建唯一 `thread_id`，并返回三种状态：

| 状态 | 含义 |
| --- | --- |
| `completed` | Workflow 已返回最终文本 |
| `needs_input` | Workflow 已中断，`clarification` 包含提示和候选 ticker |
| `failed` | 运行失败，`error` 只包含公开错误字段，不返回 Provider 密钥、内部异常文本或 traceback |

`POST /api/research/resume` 接收 `thread_id` 和 `answer`。它使用 Checkpoint 中的原始 `ResearchRequest.as_of` 重建运行上下文，不会在恢复时生成新的研究时间边界。未知 thread 返回 `404`。

## 测试覆盖

本次新增或更新的专项覆盖包括：

- 已归一化 `ResearchRequest` 跳过 Resolver 模型并规范化 ticker；
- 纯宏观计划无 target 可继续，报价计划无 target 必须澄清；
- 真实编译的 LangGraph 使用 `InMemorySaver`，完整跑通“NVDA + AAPL 多标的中断 → 回复 NVDA → 重新解析 → 加载报价 → Checker → Answer”；
- API 首次调用、独立 thread id、澄清响应和输入校验；
- API 恢复使用原 thread id 和原 `as_of`；
- 未知 thread 不执行 Graph；
- 模型调用次数、Tool 调用次数、超时和未知运行错误均映射为固定公开错误，不泄露私有细节。

`backend/examples/verify_langgraph_workflow.py` 还使用真实 DeepSeek、Longbridge 和 Macro Provider 验收了 6 个 Graph E2E 场景：

1. `NVDA 当前走势怎么看` 直接解析 NVDA 并完成；
2. `最新 CPI 是多少` 以 `absent / company_id=None` 完成纯 Macro 研究；
3. `现在股价多少` 先中断，再用 NVDA 恢复；
4. `Google 怎么看` 保留 GOOG / GOOGL 候选，再用 GOOGL 恢复；
5. `比较 NVDA 和 AAPL` 不静默选择第一只，再用 AAPL 恢复；
6. `Google 怎么看` 恢复为 `就那个` 后再次中断，未进入 Planner / Research。

三个 resume 场景都保留了原始 `request.question`，只更新经 Resolver 验证的 `request.company_id`。

2026-10-11 验收结果：

- D38 Graph / API 专项及关联回归：`49 passed`；
- 完整后端：`634 passed`；
- 全部后端生产代码 Pyright：`0 errors, 0 warnings, 0 informations`；
- D38 真实 Graph E2E：6 个场景全部通过；
- `git diff --check HEAD`：通过。

## 当前边界

- Checkpoint 使用 `InMemorySaver`，只能在当前进程存活期内恢复；服务重启、多进程或多实例部署不能保证恢复。
- 本次没有实现取消 API、持久化 Checkpoint、thread 所有权或多用户隔离。
- 多标的解析只用于保留候选并请用户选择一个，尚未实现多股同时研究。
- 离线专项 Graph E2E 使用真实 Graph 和 Checkpoint，模型、Registry 与行情 Provider 为可复现替身；另外已完成上述 6 个真实 DeepSeek / Longbridge / Macro Provider 场景联调。
- 真实联调时的周末报价超过新鲜度阈值，Quote 场景按质量规则进入 `cannot_retry / quote_unavailable`，但仍正确完成 Answer；这不代表实时报价可用。
- `InMemorySaver` 运行时对自定义 Pydantic 类型输出未来 strict msgpack 兼容性 warning；允许模块配置与持久化序列化收口与持久化 Checkpoint 一并留到后续阶段。
