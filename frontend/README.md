# Stock Agent Frontend

Stock Agent 的 React 前端。当前研究页已经接入后端研究工作流：用户提交自然语言问题后，后端创建 `thread_id`，前端通过 SSE 接收阶段变化、Answer 增量和终态事件。

## 技术栈

- React 19
- TypeScript 6
- Vite 8
- Tailwind CSS 4
- React Router 7
- Vitest + React Testing Library
- Oxlint
- pnpm

## 环境与命令

- Node.js >= 22.13
- pnpm 11.22

```bash
pnpm install
pnpm dev
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

开发服务器将 `/api` 代理到 `http://127.0.0.1:8000`，本地联调不需要开放宽泛的 CORS。

## 当前研究流程

```text
/research
  -> ResearchPage
     -> ResearchComposer
     -> useResearchRun
        -> POST /api/research
        -> 绑定后端 thread_id
        -> GET /api/research/{thread_id}/events
        -> needs_input 时 POST /api/research/resume
        -> SSETaskQueue / TextBuffer / TextTask
     -> ResearchRound
```

前端只提交用户的自然语言 `message`。证券解析、`company_ids`、研究计划、数据模式和工具选择均由后端负责。

当前支持：

- `workflow_started`：进入研究状态；
- `stage_changed`：展示 Target Resolution、Planning、Research、Checking 或 Answering 阶段；
- `answer_delta`：按接收顺序缓冲并逐步展示文本；
- `needs_input`：SSE 连接保持打开，页面展示候选 ticker 和手动输入，并使用原 `thread_id` resume；
- `completed`、`failed`、`cancelled`：在已缓冲文本展示完毕后更新终态；
- 请求失败、SSE 中断和前端展示队列失败：显示各自的安全错误状态；
- 新问题、清空页面或离开页面：中止旧的前端请求与展示任务，防止旧结果覆盖当前页面。

Cancel API 和按钮正在联调，取消失败会恢复研究状态并显示 Toast。Continue UI、页面恢复、`target_resolution` 详情卡片和六类结构化研究结果展示已移出 Day40 范围，后续处理。前端中止请求只停止当前浏览器的接收与展示，不等于取消后端任务。完整状态见 [`../docs/day40.md`](../docs/day40.md)。

## API 文件职责

```text
src/api/contracts.ts        研究命令与事件类型
src/api/request.ts          普通 JSON 请求入口、短时去重
src/api/requestLifecycle.ts 超时、重试和请求生命周期
src/api/stream.ts           SSE 连接、重连和 Last-Event-ID
src/api/sseParser.ts        增量 SSE 解析
src/api/runTransport.ts     研究启动、resume 与 cancel 命令
src/api/researchStream.ts   研究事件解析和订阅
```

`request.ts` 的公开入口：

- `requestResponse(url, options)` 返回成功的原始 `Response`；
- `request<T>(url, options)` 解析 JSON，204/205 返回 `null`；
- `get<T>(url, options)` 和 `post<TResponse, TBody>(url, body, options)` 提供常用方法；
- `RequestError.kind` 区分 `aborted`、`timeout`、`network`、`http`、`invalid_response` 和 `handler`；
- GET/HEAD 默认在首次发起后的 2 秒内共享同一次底层请求，写请求不去重；
- 共享请求的调用方可以分别取消，所有调用方都取消后才中止底层请求；
- GET/HEAD 可重试网络错误、超时、408、429 和 5xx，写请求不自动重试。

普通请求层用于有限 JSON 响应。SSE 使用独立的 `stream()` 入口，不参与普通请求的短时去重。

## SSE 边界

`stream()` 负责增量 UTF-8/SSE 解析、连接与空闲超时、可取消重连以及 `Last-Event-ID`。`researchStream.ts` 再把原始 SSE 数据转换为 `ResearchEvent`，校验事件属于预期 `thread_id` 且类型受支持，并在终态事件后关闭订阅。

当前事件身份沿用后端契约：

```text
thread_id + event_id
```

`thread_id` 标识可恢复工作流，`event_id` 在该 thread 内递增。前端不增加平行的 `run_id` 或 `seq` 概念。

`SSETaskQueue` 串行执行展示任务。Answer 文本先写入 `TextBuffer`，终态更新排在相同队列末尾，因此不会在剩余文字仍在展示时提前显示完成状态。

## 测试

当前测试覆盖：

- 普通请求的 JSON 解析、错误映射、GET 去重和订阅者取消；
- 研究事件的 thread 校验、未知事件拒绝和 terminal 关闭；
- 展示队列的顺序、abort 和动画帧等待；
- ResearchRound 的阶段、文本和错误状态；
- useResearchRun 的 thread 绑定、流式文本与失败路径；
- 路由、组件、SSE parser/stream、mock 契约和历史基础行为。

当前验收结果为 `96 passed`，`typecheck` 和 `build` 通过；Oxlint 无 error，`toast.tsx` 保留 1 条 Fast Refresh warning。

更完整的阶段计划见 [`../docs/frontend-development-plan.md`](../docs/frontend-development-plan.md)。
