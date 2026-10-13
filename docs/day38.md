# Day38：Target Resolver 的 Graph 接入与恢复

## 完成结论

Day38 的核心工作流和进程内取消已完成：Target Resolver 位于 Planner 之前，标的不唯一或无法确定时通过 LangGraph `interrupt()` 暂停，用户补充后使用同一 `thread_id` 恢复并重新验证标的。正在运行的 Workflow 由 process-local Task Registry 跟踪，可通过取消接口中止，并从仍有后续节点的 Checkpoint 继续。

```text
ResearchInput.message
  ↓
resolve_target
  ├─ resolved → planner
  ├─ absent → planner
  └─ ambiguous / unresolved
       ↓
    clarify_target → interrupt
       ↓ resume(answer)
    resolve_target 重新验证
       ↓
    planner → research → checker → answer
```

## Graph 边界

`resolve_target_node` 处理三类输入：

- 自然语言 API 创建的 `company_ids=[]` 请求会解析原始问题；
- 已归一化的内部 `ResearchRequest` 保持向后兼容，直接规范化 ticker，不重复调用 Resolver 或模型；
- 恢复时只解析用户最新补充的标的表达，不会绕过 Registry 验证。

`absent` 不会立即失败。它先进入 Planner：

- 纯宏观计划可以以 `company_ids=[]` 进入 Research；
- 报价、技术分析、决策、公司资料、财务数据和 Market Reaction 等需要证券的计划会转入澄清节点；
- Research 节点仍保留检查，防止缺少 target 的证券计划误执行。

## API 契约

`POST /api/research` 只接收自然语言 `message`。服务端为每次请求生成 UUID 形式的 `thread_id`，启动后台 Workflow，并立即返回 `status="accepted"`。客户端随后使用该 `thread_id` 订阅 SSE；replay buffer 会补发订阅前已产生的事件。

研究命令接口返回 `accepted`，Workflow 终态由 SSE 表达：

| 状态 | 含义 |
| --- | --- |
| `completed` | Workflow 已返回最终文本 |
| `needs_input` | Workflow 已中断，`clarification` 包含提示和候选 ticker |
| `failed` | 运行失败，`error` 只包含公开错误字段，不返回 Provider 密钥、内部异常文本或 traceback |
| `cancelled` | 当前进程通过 cancel API 主动取消了运行中的 Workflow |

`POST /api/research/resume` 接收 `thread_id` 和 `answer`。它使用 Checkpoint 中的原始 `ResearchRequest.as_of` 重建运行上下文，不会在恢复时生成新的研究时间边界。接受执行时返回 `accepted`，未知 thread 返回 `404`。

`POST /api/research/{thread_id}/cancel` 只取消当前进程 Task Registry 中正在运行的任务。接受取消时返回 `cancelling`，并通过 SSE 发布 `cancelled`；thread 不在运行时返回 `404`。

`POST /api/research/{thread_id}/continue` 用于继续被取消但 Checkpoint 仍有后续节点的 Workflow。接受执行时返回 `accepted`；等待用户澄清时必须使用 `/resume`；已完成或仍在等待输入的 Workflow 对 `/continue` 返回 `409`。

同一 `thread_id` 同时只允许一个 active run。Task Registry 只管理执行中的 `asyncio.Task`，Graph State 和恢复位置仍由 LangGraph Checkpointer 管理。

## 测试覆盖

本次新增或更新的专项覆盖包括：

- 已归一化 `ResearchRequest` 跳过 Resolver 模型并规范化 ticker；
- 纯宏观计划无 target 可继续，报价计划无 target 必须澄清；
- 真实编译的 LangGraph 使用 `InMemorySaver`，完整跑通 NVDA 与 AAPL 多标的直接研究，并分别加载报价；
- API 首次调用返回 `accepted`、服务端生成独立 thread id、澄清事件和输入校验；
- API 恢复使用原 thread id 和原 `as_of`；
- 未知 thread 不执行 Graph；
- 初始请求拒绝客户端提供 `thread_id`，避免覆盖旧 Workflow；
- 同一 thread 并发执行被拒绝，不同任务终态后 Registry 正确清理；
- cancel API 取消运行中的 Graph 并发布 `cancelled` 事件；未运行 thread 返回 `404`；
- 非 cancel API 引起的外部 `asyncio.CancelledError` 继续向上传播，不伪装成用户主动取消；
- continue 只在 Checkpoint 存在且有后续节点时继续，拒绝未知、等待输入和已完成状态；
- 模型调用次数、Tool 调用次数、超时和未知运行错误均映射为固定公开错误，不泄露私有细节。

`backend/examples/verify_langgraph_workflow.py` 还使用真实 DeepSeek、Longbridge 和 Macro Provider 验收了 6 个 Graph E2E 场景：

1. `NVDA 当前走势怎么看` 直接解析 NVDA 并完成；
2. `最新 CPI 是多少` 以 `absent / company_ids=[]` 完成纯 Macro 研究；
3. `现在股价多少` 先中断，再用 NVDA 恢复；
4. `Google 怎么看` 保留 GOOG / GOOGL 候选，再用 GOOGL 恢复；
5. 历史验收中的 `比较 NVDA 和 AAPL` 曾要求选择单只；当前 `company_ids` 升级后改为保留两只并进入多证券研究；
6. `Google 怎么看` 恢复为 `就那个` 后再次中断，未进入 Planner / Research。

resume 场景保留原始 `request.question`，只合并经 Resolver 验证的 `request.company_ids`。

2026-10-11 验收结果：

- Task Registry + Research API 专项：`39 passed`；
- 完整后端：`647 passed`；
- 全部后端生产代码 Pyright：`0 errors, 0 warnings, 0 informations`；
- D38 真实 Graph E2E：6 个场景全部通过；
- `git diff --check HEAD`：通过。

## 当前边界

- Checkpoint 使用 `InMemorySaver`，只能在当前进程存活期内恢复；服务重启、多进程或多实例部署不能保证恢复。
- Task Registry 和 cancel / continue 都是 process-local；未实现持久 Run Metadata、worker ownership、分布式取消、thread 所有权或多用户隔离。
- `asyncio.Task.cancel()` 使用协作式取消，不能强制终止正在执行的同步阻塞代码或已由远端服务接收的工作。
- 多标的请求已开始升级为同时研究，证券级结果按 `results['companies'][company_id]` 保存；完整 API、旧 Agent 与真实联调尚未收口，见 Day39 文档。
- 离线专项 Graph E2E 使用真实 Graph 和 Checkpoint，模型、Registry 与行情 Provider 为可复现替身；另外已完成上述 6 个真实 DeepSeek / Longbridge / Macro Provider 场景联调。
- 真实联调时的周末报价超过新鲜度阈值，Quote 场景按质量规则进入 `cannot_retry / quote_unavailable`，但仍正确完成 Answer；这不代表实时报价可用。
- `InMemorySaver` 运行时对自定义 Pydantic 类型输出未来 strict msgpack 兼容性 warning；允许模块配置与持久化序列化收口与持久化 Checkpoint 一并留到后续阶段。
