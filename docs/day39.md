# Day39：Research SSE 与多证券请求升级

## 当前结论

Day39 的进程内 SSE 主链路已经搭通，并把 LangGraph 主工作流从单个 `ResearchRequest.company_id` 升级为 `company_ids`。事件模型、有界 subscriber queue、短线 replay buffer、terminal TTL、Graph stream 事件转换、SSE 编码和进程级清理任务均已有专项测试；多证券 Resolver、Research 结果分组和共享 Macro 数据也已进入主流程。

Day39 当前范围已完成。旧 Agent 的 `company_ids` 迁移和真实 HTTP SSE 端到端验收已经收口；`needs_input` 保持连接并继续 heartbeat，resume 后延续同一 thread 的事件序列。事件身份正式使用 `thread_id + event_id`，阶段事件只表示进入当前阶段，不再扩展 `run_id / seq` 或独立节点完成事件。

## 完成度矩阵

| 范围 | 状态 | 说明 |
| --- | --- | --- |
| `company_ids` LangGraph 主流程 | 已完成 | Resolver、Planner、Research、Checker、Answer 和 API 请求已使用复数标的 |
| 旧 Manual / LangChain Agent | 已完成 | 请求序列化、Runtime Context 和 Tool target guard 均已迁移到 `company_ids` |
| 结构化 SSE 事件与编码 | 已完成 | 已有 workflow、stage、target、answer、clarification 和终态事件 |
| Answer 临时增量与最终结果 | 已完成 | HTTP 验收确认 `completed.data.result` 与最终 checkpoint 的 `output` 一致 |
| heartbeat 与短线 replay | 已完成 | HTTP 验收覆盖 heartbeat、`Last-Event-ID`、过期游标 `409` 和 5 分钟 terminal replay |
| 慢客户端与内存生命周期 | 已完成 | queue 上限 256；overflow 断开 subscriber；terminal 到期后完整清理 thread 状态 |
| clarification / resume SSE | 已完成 | 同一 HTTP 连接经过 `needs_input`、heartbeat、resume 和 completed，并保留原问题 |
| cancel SSE | 已完成 | HTTP 验收确认 `cancelled` 是唯一终态，后面没有 token 或 `completed` |
| 前端真实 SSE 接入 | 未开始 | 属于 D40；当前前端只有通用 SSE transport/parser，未接入研究页面 |

## `company_ids` 契约

`ResearchRequest` 现在使用：

```python
company_ids: list[str] = Field(
    default_factory=list,
    max_length=20,
)
```

- 无证券的宏观问题使用空列表；
- 一个证券使用 `['NVDA']`；
- 多证券问题保留解析顺序，例如 `['NVDA', 'AAPL']`；
- 旧字段 `company_id` 因 `extra='forbid'` 被拒绝；
- Resolver 的 `resolved_targets` 可以包含多个 ticker，只有仍存在歧义或未解析 mention 时才中断；
- Research 的证券级结果保存在 `results['companies'][company_id]`，Macro Snapshot 等共享结果保留在 `results` 顶层。

当前模型只限制证券数量不超过 20，尚未对单个列表项声明非空、最大长度、唯一性或统一大写。这是待确定的请求契约，不在本次检查中补业务规则。

## SSE 事件与重放

事件订阅接口为：

```text
GET /api/research/{thread_id}/events
```

当前事件类型：

| 事件 | 用途 |
| --- | --- |
| `workflow_started` | 一次 start / resume / continue 开始 |
| `stage_changed` | 进入 Target Resolution、Planning、Research、Checking 或 Answering 阶段 |
| `target_resolution` | 标的解析结果 |
| `answer_delta` | Answer 节点的临时文本增量 |
| `needs_input` | Workflow 等待用户澄清 |
| `completed` | 最终文本已生成 |
| `failed` | 运行失败后的公开错误 |
| `cancelled` | 当前运行被取消 |

每个 thread 的 `event_id` 从 1 开始单调递增。进程内 `deque` 默认保留最近 2000 条事件；客户端可使用查询参数 `last_event_id` 或 `Last-Event-ID` header 请求缺失事件。游标早于保留窗口或大于最新事件时返回 `409`。连接空闲 15 秒输出一次 SSE heartbeat；`completed / failed / cancelled` 后关闭事件流。

事件身份契约保持当前实现：`thread_id` 标识整个可恢复研究会话，`event_id` 在该 thread 内跨 start / resume / continue 单调递增。不另外引入 `run_id` 或 `seq` 别名。`stage_changed` 只表示工作流进入某个阶段；最终状态由 `completed / failed / cancelled` 表达，不增加独立 node completed 事件。

`needs_input` 不是终态事件。服务端发出它之后保持当前 SSE 连接并继续 heartbeat；客户端调用 resume 后，`workflow_started(execution="resume")` 和后续事件继续使用同一 `thread_id` 与单调递增的 `event_id`。原始研究问题不会被 clarification answer 替换。

每个 subscriber queue 最多保留 256 个待发送事件。慢客户端导致 queue 满时，Event Store 不会阻塞 Workflow，也不会丢弃单个事件继续发送，而是清空并关闭该 subscriber；客户端使用最后收到的 `Last-Event-ID` 重新连接后，从公共 replay buffer 补齐事件。

terminal thread 的 SSE 状态保留 5 分钟，期间仍可 replay，也允许 `/continue` 通过新的 `workflow_started` 撤销过期时间。5 分钟后，进程级 sweeper 和访问时清理会删除该 thread 的 buffer、最后 event id、subscriber 和过期元数据。SSE Event Store 过期不影响 LangGraph checkpoint；过期后同一 thread 的新事件可以重新从 event id 1 开始。

事件与 Checkpoint 分层：stream chunk 只负责过程展示，最终 `completed` 内容从 Graph 的最新 checkpoint 读取。当前 event store 仍是 process-local，服务重启后不会保留事件。

## 已有测试覆盖

新增：

- `test_research_request_company_ids.py`：复数标的、空列表、旧字段拒绝和 20 个上限；
- `test_research_event_store.py`：thread 内单调序号、跨 thread 隔离、实时广播、游标 replay、窗口截断、慢 subscriber 关闭、terminal TTL 清理和 continue 撤销过期；
- `test_research_sse.py`：cursor 优先级与校验、SSE wire format、replay/live terminal 关闭、overflow sentinel 关闭和取消订阅，以及真实 FastAPI 路由的 terminal replay 与过期游标 `409`；
- `test_research_sse_http.py`：HTTP 路由端到端验证 `needs_input` 保持连接与 heartbeat、resume 同序列、`Last-Event-ID` 缺失补发、cancel 终态、最终 checkpoint 一致性和 terminal TTL；
- `test_research_stream_runner.py`：节点阶段、Answer delta、完成事件序列和中断事件序列；
- `test_langgraph_multi_company.py`：按证券定位缺失信息、共享 Macro 只检查一次、Provider warning 不跨证券污染；
- 更新 Graph、Planner、Target 和 `/api/runs` 测试，使用 `company_ids` 和 `results['companies']`。

2026-10-12 当前本地结果：

- Event Store、SSE 与 stream runner 专项：`27 passed`；
- Manual、LangChain Agent 和 LangChain Tool 回归：`126 passed`；
- 完整后端回归：`681 passed, 1 failed`；唯一失败是已记录的 Day36 空历史语义差异，与本次迁移无关，本轮没有改动该业务逻辑；
- Pyright 生产代码：`0 errors`；
- `git diff --check HEAD`：通过。

## 已确认的范围边界

- 使用 `thread_id + event_id`，不增加 `run_id + seq`；
- `stage_changed` 表示进入阶段，不增加节点完成事件；
- `needs_input` 后保持 SSE 连接，resume 继续同一事件序列。

### 非阻塞后续项

1. 订阅不存在的 thread 时，当前会建立空订阅并持续 heartbeat。需要定义返回 `404`，还是允许客户端先订阅后启动 Workflow。
2. 确认 Checker 的空结果语义：Earnings / Macro Reaction history 与 Knowledge 当前只有 `None` 才视为不可用，空列表会被视为研究充分；现有 Day36 测试仍认为空历史应为缺失。
3. 决定 `company_ids` 列表项是否在请求模型层强制非空、长度限制、去重和统一大写；当前只限制最多 20 项。

- 前端研究页面接入真实 SSE、工作流状态展示和 token 渲染属于 D40；
- PostgreSQL Checkpoint、持久 Run Metadata、worker ownership 和分布式取消属于后续工程化；
- Event Store 仍可保持单进程、5 分钟短线 replay，不需要在 Day39 引入 Redis 或分布式事件总线。

Day36 空历史语义需要独立确认，不应混入 Day39 SSE 逻辑。
