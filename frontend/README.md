# Stock Agent Frontend

Stock Agent 的独立前端工程。FE01 已完成工程初始化和公开契约；FE02 的本地 Mock 单轮对话功能已完成，统一补测阶段尚未开始。当前不调用真实后端或模型。

## 技术栈

- React 19
- TypeScript 6
- Vite 8
- Tailwind CSS 4（官方 Vite 插件）
- React Router 7
- Vitest + React Testing Library
- Oxlint
- pnpm

## 环境

- Node.js >= 22.13
- pnpm 11.22

## 命令

```bash
pnpm install
pnpm dev
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

开发服务器将 `/api` 请求代理到 `http://127.0.0.1:8000`，因此后续可以同源调用本地 FastAPI，无需在开发阶段开放宽泛的 CORS。

目标对话接口为 `POST /api/chat/runs`，请求只包含用户自然语言 `message` 和可选 `conversation_id`。当前后端尚未实现该入口；FE03 联调前由服务端把公开对话请求归一化为现有内部 `ResearchRequest`。前端不会自行生成 `company_id`、`data_mode` 或 `as_of`。

## 当前调用链

```text
/research route
  → ResearchPage
      ├─ ResearchComposer
      ├─ useResearchRun
      │   └─ RunTransport.createRun
      └─ ResearchConversation
          └─ ResearchResponse
```

目录职责：

```text
src/app       路由配置
src/pages     路由页面和依赖组装
src/features  研究业务组件、状态 Hook 和页面状态类型
src/api       公开数据契约与传输接口
src/mocks     可替换的本地 Fake Transport 和固定响应
src/test      测试环境配置
```

`useResearchRun` 初始化时不会调用 `createRun`。用户提交后依次进入 submitting、received 或 request_failed。新一轮提交前，上一轮已结束的用户消息和回复存入本地 `history`，页面按顺序展示历史与当前轮。“清空全部对话”清除全部本地历史；刷新或离开页面后不保留，也不把历史传给模型。

输入框使用普通 `onSubmit` 事件：先阻止浏览器默认提交，再读取并 trim 消息，空输入直接返回，合法消息交给 Hook。等待期间立即显示加载状态并禁用输入和发送按钮。

默认 Fake Transport 立即返回固定的 completed 响应，内容只用于教学验证，不会根据问题做真正的研究。资料不足、Agent 失败和取消的公开响应也已具备展示分支。清空、离开页面时会通过已有 AbortController 让未完成的响应失效，不代表后端取消接口或持久会话删除。

开发阶段只运行 `typecheck`、`lint`、`build`，不新增测试。统一补测时再更新现有 FE01 测试与 Router 上下文。

## 共用 HTTP 请求层

`src/api/request.ts` 提供 `request(url, options)` 和 `requestJson(url, options)`，沿用原生 fetch 选项及 `signal`，无需安装请求库。当前仅建立封装，默认页面仍使用 Fake Transport。

- `request` 返回成功的原始 Response；适合非 JSON 接口。
- `requestJson` 返回 `unknown`，204/205 返回 null；具体 API 必须校验响应结构，不直接断言成业务类型。
- `RequestError.kind` 区分 `aborted`、`timeout`、`network`、`http`、`invalid_response`、`handler`；message 不包含原始服务端正文或异常。handler 用于 SSE 业务回调抛错，不自动重连。
- `isRequestAborted(error)` 用于静默结束取消请求，不应显示“请求失败”。读取 JSON 期间取消也会归为 aborted。
- HTTP 错误保留 `status` 和未消费正文的 `response`，由具体 API 决定如何读取 422 等业务内容；不把原始正文直接展示给用户。
- CORS、断网、DNS 等浏览器不可区分的故障统一归为 network；CORS 要结合开发者工具检查并修复服务端配置，不使用 no-cors 绕过。
- 合法 JSON 中的 Agent failed/cancelled 或其他业务错误不由请求层解释。
- GET/HEAD 默认在首次发起后的 2 秒内共享同一次请求及其响应，不延长有效期；可用 `dedupeTtlMs: 1000` 改为 1 秒。URL（包含查询参数）、方法、请求头及其他 fetch 选项相同才共享。
- POST/PUT/PATCH/DELETE 等其他方法永远不去重，即使配置 dedupe 也不会开启。请求或响应声明 no-store/no-cache 时不保留短时缓存；传输失败不缓存。
- 各调用方收到独立 Response 副本。取消只结束当前调用方；全部调用方在响应完成前都取消时，才取消底层请求。
- 强制刷新使用 `dedupe: false`。缓存仅在当前页面内存中存在。
- 普通请求层完整读取响应正文（含错误响应），让超时覆盖正文下载，并保留未消费的原 Response 给 API。它只适用于有限响应；SSE 使用独立的 stream 入口，关闭 dedupe 不会让普通封装变成流式请求。

### 请求生命周期与重试

```text
request / requestJson（重复请求共享管理）
  → performRequest（请求级 Controller + 重试循环）
      → attemptRequest（每次新建 Controller + 超时 + fetch/正文读取）
      → 可取消的指数退避等待
```

文件职责：`request.ts` 管理共享及公开入口；`requestLifecycle.ts` 管理普通请求的超时和重试；`requestControl.ts` 提供普通请求/SSE 共用的取消桥接、可取消等待与退避；`requestErrors.ts` 定义安全错误。原有 RequestError/isRequestAborted 导入路径保持不变。

- `timeout` 默认 10000ms，是每次尝试的超时，不是整个重试周期的总超时；设为 0 可关闭。
- `retries` 默认 2，表示最多额外两次尝试，可配置 0～5；`retryDelay` 默认 500ms，使用指数退避和随机抖动，指数部分上限 30 秒，并尊重可读的 Retry-After。
- 仅 GET/HEAD 自动重试网络错误、超时、408、429、5xx；主动取消、400/401/403/404/422 和无效 JSON 不重试。
- POST/PUT/PATCH/DELETE 等其他方法既不共享也不自动重试，即使显式设置 retries 也不会自动重复写操作。
- 用户取消会中止当前尝试或退避等待。每次尝试清理自身 timer/listener 后才进入退避，不复用已经 aborted 的 Controller。
- 共享请求的订阅者仍可各自取消；最后一个订阅者取消才中止整个重试生命周期。共享 key 包含超时/重试配置，不让不同策略的调用方借用另一套配置。

```ts
const body: unknown = await requestJson('/api/example', {
  signal: controller.signal,
  timeout: 5000,
  retries: 2,
  retryDelay: 500,
  dedupeTtlMs: 1000,
})
// 由具体 API 校验 body，并解释业务结果。
```

使用顺序：具体 API 调用 `requestJson` → 校验 unknown → 返回业务结果；Hook 处理页面状态。请求层不弹窗、不跳转、不生成业务字段，POST 的 JSON 序列化和 Content-Type 由具体 API 设置。合法业务错误不进入重试循环。

## SSE 传输入口（未接入页面/后端）

按最新开发要求建立通用 `src/api/stream.ts`；这不是 FE06 后端联调或恢复验收完成。现有页面继续使用 Fake Transport，createRun 不在本次范围。

```text
stream（连接生命周期 Controller，可选业务 key 替换）
  → connectOnce（每次连接新建 Controller）
      → fetch + 建立连接超时
      → 增量 UTF-8 / SSE 解析 + 等待数据超时
      → onEvent（顺序等待业务处理）
  → GET 断线后可取消退避，再携带 Last-Event-ID 连接
```

- `stream(url, options): Promise<void>`，onEvent 必填；它收到 `{ event, data, id }`，data 为原始字符串。解析和业务错误由具体 API 负责，不会把 chunk 当成一条消息。
- `connectTimeout` 默认 10 秒，合法 SSE 响应头到达后停止；`idleTimeout` 默认 30 秒，每次收到字节（包括注释心跳）重置。两者设为 0 可关闭。顺序处理业务回调时暂停空闲计时，避免消费端背压误报。
- onEvent 返回 false 时正常关闭；HTTP 204 也正常结束。未知 EOF 视为断线，不自行猜测业务已经完成。不会自动识别 `[DONE]`、run_finished 或任何业务 JSON。
- GET 默认最多额外重连 3 次，基础延迟 1 秒，指数部分上限 30 秒并加抖动；尊重 SSE `retry:` 和可读 Retry-After 的最小等待时间。maxReconnects 是整个生命周期的总额外次数，不因收到消息而重置。
- POST/其他方法只连接一次，即使 reconnect=true 也不重发。推荐后端未来采用 POST 创建任务 + GET 订阅同一 run_id，不能在断线后重新创建任务。
- 重连保存已成功交付的事件 id；id-only 完整块可更新游标，空 id 重置。初次恢复可传 lastEventId。服务端仍需支持事件补发，业务层仍需防止重复应用；本封装不承诺 exactly-once。
- SSE 不使用普通请求的 2 秒缓存。默认连接彼此独立；显式传 connectionKey 时只替换同 key 的 GET 连接，其他会话不会按 URL 被自动取消，POST 不参与替换。
- 手动 abort、回调异常、认证/参数错误、错误 Content-Type 等不会重连。用户取消也会中断 reader、回调等待或退避，不等于取消后端 Agent 任务。
- `sseParser.ts` 支持跨 chunk 的 CR/LF/CRLF、UTF-8、多行 data、注释、event/id/retry；丢弃 EOF 的残缺事件。maxBufferChars 默认一百万字符，超出立即停止。[解析依据：WHATWG SSE](https://html.spec.whatwg.org/multipage/server-sent-events.html#parsing-an-event-stream)。

下面仅演示传输层用法，地址和 done 事件不是当前后端契约：

```ts
import { stream } from './api/stream'
import { isRequestAborted } from './api/request'

const controller = new AbortController()
try {
  await stream('/api/example/events', {
    signal: controller.signal,
    connectTimeout: 5000,
    idleTimeout: 30000,
    onEvent: async (event) => {
      // 在具体 API 中校验/处理 event.data；必要时按 run_id + 序号去重。
      return event.event !== 'done'
    },
  })
} catch (error) {
  if (!isRequestAborted(error)) {
    // 交给调用方展示安全错误，不显示原始异常。
  }
}
// 页面卸载或停止接收：controller.abort()
```

业务步骤见 `../docs/frontend-development-plan.md`。
