# FE02 TODO：从最小对话页面到合理抽象

> 本文是 FE02 的详细执行清单。`docs/frontend-development-plan.md` 的 FE02 章节同步目标、顺序和边界，不再保留旧的复杂 Hook 方案。

## 当前交付状态

- [x] FE02 本地 Mock 单轮对话业务已实现，包括输入、请求状态、用户消息、结构化结果、安全错误和清空。
- [x] 支持连续提交并保留之前已结束的本地对话；清空全部历史，刷新或离开页面不保留，不传给模型。
- [x] Page 已直接连接 Composer 与 Hook，Conversation 按联合类型展示响应，不使用 `as any`。
- [x] 输入有明确 label；提交期间禁用输入和按钮，并显示“研究中”。
- [x] 四种合法 Agent 终态的展示分支已完成。
- [x] 类型检查、lint、生产构建通过。
- [x] 浏览器手动验证：completed、资料不足、Agent failed/cancelled、延迟加载与禁用输入、Transport 抛错、清空当前对话。
- [x] 桌面与 375px 小屏手动检查通过，长文本和 Run ID 可以换行。
- [ ] FE02.10 统一补测尚未开始；本次不新增或修改测试文件。

以下章节保留开发过程说明。知识理解类清单由学习者确认，不因代码交付自动勾选。

## 1. 开发方式

FE02 不再从独立 Hook 或细分组件开始，而是遵循：

```text
先看页面在哪里使用
    ↓
在页面内完成最小可运行流程
    ↓
确认调用时机和数据流
    ↓
观察代码中真实出现的问题
    ↓
再抽离 Hook、类型和展示组件
    ↓
功能全部完成后统一补测试
```

开始每一步前，必须先说明：

1. 本步解决什么用户问题；
2. 代码放在哪个文件；
3. 谁调用它；
4. 什么时候调用；
5. 输入和输出是什么；
6. 本步明确不实现什么；
7. 本步是“只搭架构”还是“实现业务逻辑”。

如果范围不明确，编码前先确认，不自行扩大任务。

开发阶段不新增或修改前端测试。每一步只运行：

```text
pnpm typecheck
pnpm lint
pnpm build
```

等 FE02 业务功能全部完成后，再进入统一测试阶段。

---

## 2. FE02 最终目标

完成一个使用本地 Mock Transport 的单轮对话研究页面：

```text
用户进入 /research
    ↓
输入自然语言问题
    ↓
空输入在 Composer 内被拦截
    ↓
页面调用 Fake RunTransport
    ↓
页面显示用户消息和加载状态
    ↓
页面收到结构化 RunResponse
    ↓
页面展示事实、推断、证据、缺失信息或安全错误
```

公开请求只包含：

```ts
interface CreateResearchRunRequest {
  message: string
  conversation_id?: string
}
```

FE02 不要求用户填写或理解：

```text
company_id
data_mode
as_of
工具选择
RAG 策略
新闻或宏观数据源
```

---

## 3. 当前已有架构

以下记录已经完成的架构基础；业务交付状态见文档顶部。

- [x] `BrowserRouter` 已接入应用入口。
- [x] `/` 重定向到 `/research`。
- [x] `/research` 对应 `ResearchPage`。
- [x] 未知路由对应 `NotFoundPage`。
- [x] `App` 可以注入 `RunTransport`。
- [x] `ResearchPage`、`ResearchComposer`、`ResearchConversation` 文件已建立。
- [x] `useResearchRun` 和 `ResearchViewState` 文件已建立。
- [x] `RunTransport` 接口和最小 Fake Transport 已建立。
- [x] `CreateResearchRunRequest`、`RunResponse` 公开契约已在 FE01 完成。

当前架构关系：

```text
main.tsx
  → App
  → AppRoutes
  → ResearchPage
      ├─ ResearchComposer
      ├─ useResearchRun
      ├─ ResearchConversation → ResearchResponse
      └─ RunTransport
```

这些文件后续按步骤填充，不能因为文件已经存在就直接实现最终复杂逻辑。

---

## 4. 新的执行顺序

```text
FE02.1 看懂 Route 与 Page 的装配关系
    ↓
FE02.2 完成最小输入组件
    ↓
FE02.3 在 Page 内跑通最小请求
    ↓
FE02.4 在 Page 内直接显示最小结果
    ↓
FE02.5 根据已经出现的页面状态整理类型
    ↓
FE02.6 将请求生命周期抽离为 useResearchRun
    ↓
FE02.7 根据已经出现的 JSX 抽离展示组件
    ↓
FE02.8 补齐 FE02 范围内的终态和安全错误
    ↓
FE02.9 完成页面体验和代码收口
    ↓
FE02.10 功能完成后统一补测试
```

---

## 5. FE02.1：理解 Route、App 与 Page

### 本步性质

只理解和检查架构，不实现业务逻辑。

### 文件

```text
frontend/src/main.tsx
frontend/src/App.tsx
frontend/src/app/routes.tsx
frontend/src/pages/ResearchPage.tsx
frontend/src/pages/NotFoundPage.tsx
```

### 需要理解的调用链

```text
main.tsx 创建 React 应用
    ↓
BrowserRouter 提供浏览器路由上下文
    ↓
App 负责注入 Transport
    ↓
AppRoutes 根据 URL 选择页面
    ↓
/research 渲染 ResearchPage
```

### TODO

- [ ] 能说明为什么 `BrowserRouter` 放在 `main.tsx`。
- [ ] 能说明 `App` 为什么不直接处理研究请求。
- [ ] 能说明 Route 与 Page 的区别。
- [ ] 能从 `/research` 找到最终渲染的 `ResearchPage`。
- [ ] 能说明 `RunTransport` 为什么从 App 注入。

### 本步不做

- 不写请求逻辑；
- 不写 Hook 状态机；
- 不写结果渲染；
- 不写测试。

---

## 6. FE02.2：完成最小输入组件

### 用户问题

用户需要输入一段自然语言并点击发送。

### 文件

```text
frontend/src/features/research/ResearchComposer.tsx
```

### 使用位置

```tsx
<ResearchComposer
  disabled={false}
  onSubmit={handleSubmit}
/>
```

### 组件接口

```ts
interface ResearchComposerProps {
  disabled: boolean
  onSubmit: (
    request: CreateResearchRunRequest,
  ) => void | Promise<void>
}
```

### 内部逻辑

```text
用户提交 form
    ↓
读取 message
    ↓
trim()
    ↓
空字符串：直接 return
    ↓
合法消息：onSubmit({ message })
```

### TODO

- [ ] 从公开契约导入 `CreateResearchRunRequest`。
- [ ] 不在组件内重复定义请求类型。
- [ ] 对输入执行 `trim()`。
- [ ] 空字符串或纯空格直接返回，不发送请求。
- [ ] 合法输入只提交 `{ message }`。
- [ ] `disabled=true` 时不能重复提交。
- [ ] 不生成 `company_id`、`data_mode` 或 `as_of`。

### 完成标准

能明确说明：

```text
ResearchComposer 只收集输入
它不知道 createRun
它不知道 Mock 或 HTTP
它不展示 Agent 结果
```

---

## 7. FE02.3：在 Page 内跑通最小请求

### 为什么先写在 Page

此时先看清最短调用链，不立即把逻辑藏进 Hook。

### 文件

```text
frontend/src/pages/ResearchPage.tsx
frontend/src/api/runTransport.ts
frontend/src/mocks/fakeRunTransport.ts
```

### 最小调用链

```text
ResearchComposer.onSubmit
    ↓
ResearchPage.handleSubmit
    ↓
runTransport.createRun(request)
    ↓
Promise<RunResponse>
```

### 页面内最小实现

第一版只需要：

```ts
async function handleSubmit(
  request: CreateResearchRunRequest,
) {
  const response = await runTransport.createRun(request)
  // 下一步再显示 response
}
```

### TODO

- [ ] 先在 `ResearchPage` 定义 `handleSubmit`。
- [ ] 将 `handleSubmit` 传给 `ResearchComposer.onSubmit`。
- [ ] 在 `handleSubmit` 内调用注入的 `runTransport.createRun`。
- [ ] 明确 `createRun` 在用户提交后才执行，不在页面渲染时执行。
- [ ] Fake Transport 只返回 FE01 已有的固定 `RunResponse`。

### 本步不做

- 不使用 `requestId`；
- 不使用 `AbortController`；
- 不解析 HTTP 422；
- 不实现真实 fetch；
- 不抽离 Hook；
- 不写测试。

---

## 8. FE02.4：在 Page 内直接显示最小结果

### 用户问题

用户提交以后，需要知道问题已经发送，并看到 Agent 返回的结构化结果。

### 先使用最简单的页面状态

```ts
const [userMessage, setUserMessage] = useState('')
const [isSubmitting, setIsSubmitting] = useState(false)
const [response, setResponse] = useState<RunResponse | null>(null)
```

### 调用顺序

```text
handleSubmit(request)
    ↓
保存 request.message
    ↓
setIsSubmitting(true)
    ↓
await runTransport.createRun(request)
    ↓
setResponse(response)
    ↓
setIsSubmitting(false)
```

### TODO

- [ ] 提交后立即保留用户消息。
- [ ] 请求期间显示“研究中”。
- [ ] 收到结果后显示 `run_id` 和 `status`。
- [ ] 第一版可以直接在 `ResearchPage` 内写最小 JSX。
- [ ] 暂时不创建 `RunSummary`、`ClaimList` 等细分组件。

### 为什么暂时不抽组件

先看到真实 JSX 和重复结构，才能判断组件边界。不能为了目录好看提前创建空组件。

---

## 9. FE02.5：从页面实际状态整理类型

### 抽象时机

当页面已经同时维护用户消息、加载状态和响应时，再把不可能同时成立的状态整理为联合类型。

### 文件

```text
frontend/src/features/research/type.ts
```

### FE02 最小状态

```ts
type ResearchViewState =
  | {
      kind: 'idle'
    }
  | {
      kind: 'submitting'
      userMessage: string
    }
  | {
      kind: 'received'
      userMessage: string
      response: RunResponse
    }
  | {
      kind: 'request_failed'
      userMessage: string
      errorMessage: string
    }
```

### TODO

- [ ] 从页面已有状态推导联合类型，而不是先写复杂状态机。
- [ ] `submitting` 保留 `userMessage`。
- [ ] `received` 同时保存用户消息和 `RunResponse`。
- [ ] 网络或 Mock 抛错使用统一 `request_failed`。
- [ ] 不在 FE02 增加暂时用不到的字段。

### FE02 暂不需要

```text
requestId
AbortController
request_invalid
checkpoint
SSE event sequence
```

FE02 提交期间禁用输入，因此当前不会出现并行请求竞态。等 FE03 真实 HTTP 联调需要重复提交或重新请求时，再引入竞态保护。

---

## 10. FE02.6：抽离 useResearchRun

### 为什么现在才抽离

到这一步，`ResearchPage` 已经出现以下与布局无关的代码：

```text
保存页面状态
调用 createRun
处理 Promise 成功
处理通用失败
恢复 idle
```

这些代码才构成 Hook 的真实抽象理由。

### 文件

```text
frontend/src/features/research/useResearchRun.ts
```

### 使用位置

```ts
const {
  state,
  submit,
  reset,
} = useResearchRun(
  runTransport.createRun,
)
```

### 输入

```ts
type CreateRun = (
  request: CreateResearchRunRequest,
  signal?: AbortSignal,
) => Promise<RunResponse>
```

FE02 不使用 `signal`，只是保持 Transport 接口以后可以扩展。

### 输出

```ts
{
  state: ResearchViewState
  submit: (
    request: CreateResearchRunRequest,
  ) => Promise<void>
  reset: () => void
}
```

### 内部执行顺序

```text
Hook 初始化
→ 只创建 idle 状态，不调用 createRun

用户提交
→ ResearchComposer 调用 submit(request)
→ submit 设置 submitting
→ submit 调用 createRun(request)
→ 成功后设置 received
→ 抛错后设置 request_failed

用户 reset
→ 状态恢复 idle
```

### TODO

- [ ] 初始化时保持 `idle`。
- [ ] 确认 Hook 初始化不会调用 `createRun`。
- [ ] 只在 `submit()` 内调用 `createRun`。
- [ ] 请求开始进入 `submitting`。
- [ ] Promise resolve 后进入 `received`。
- [ ] Promise reject 后进入通用 `request_failed`。
- [ ] `reset()` 只恢复 `idle`。
- [ ] 页面只负责组装和渲染，不再包含请求生命周期。

### 本步不做

- 不解析 HTTP 422；
- 不处理旧响应覆盖；
- 不实现浏览器取消；
- 不实现后端任务取消；
- 不实现断点恢复；
- 不写测试。

---

## 11. FE02.7：根据真实 JSX 抽离展示组件

### 抽象原则

先从已经可以工作的 `ResearchPage` 移动代码，不提前设计大量组件。

### 第一轮只抽两个组件

```text
frontend/src/features/research/ResearchConversation.tsx
frontend/src/features/research/ResearchResponse.tsx
```

职责：

```text
ResearchConversation
→ 根据 ResearchViewState 组织用户消息、加载状态和 Agent 消息

ResearchResponse
→ 根据 RunResponse.status 展示结构化结果
```

### TODO

- [ ] 用户消息和 Agent 消息视觉区分。
- [ ] submitting 显示用户消息和加载状态。
- [ ] received 显示用户消息和结构化结果。
- [ ] request_failed 显示统一安全提示。
- [ ] `completed` 展示 facts、inferences、evidence ID、run ID 和 data mode。
- [ ] `insufficient_information` 突出 missing information。
- [ ] `failed` 只显示公开 `error`。
- [ ] `cancelled` 明确显示任务已取消。

只有当 `ResearchResponse` 已经明显过长或出现重复 JSX 时，才继续抽离：

```text
RunSummary
ClaimList
EvidenceBadge
MissingInformation
PublicErrorPanel
```

这批组件不是 FE02 开始阶段的前置任务。

---

## 12. FE02.8：补齐本阶段错误边界

FE02 只处理已经真实存在的两类结果。

### Agent 终态

以下是合法 `RunResponse`，不属于网络异常：

```text
completed
insufficient_information
failed
cancelled
```

### Transport 抛错

Fake Transport 或未来 Transport 抛出异常时，FE02 统一显示：

```text
暂时无法完成请求，请稍后重试。
```

不得显示原始异常、stack、密钥或模型内部信息。

### FE02 不实现 HTTP 422 字段格式化

空输入已经由 `ResearchComposer` 拦截。真实 HTTP 422 要等 FE03 接入 `/api/chat/runs` 后，根据实际返回协议处理。

当前不创建：

```text
formatValidationMessages.ts
RunValidationError
HTTP 错误解析器
```

---

## 13. FE02.9：页面体验与代码收口

TODO：

- [ ] 输入框拥有明确 label。
- [ ] 提交期间输入框和按钮禁用。
- [ ] 状态变化不只依赖颜色表达。
- [ ] fixture 明确标记为教学模拟数据。
- [ ] 长文本可以正常换行。
- [ ] 页面在常见桌面和移动宽度可阅读。
- [ ] App、Page、Hook、Transport、组件职责与 README 一致。
- [ ] 删除没有使用的提前抽象和空文件。
- [ ] `pnpm typecheck` 通过。
- [ ] `pnpm lint` 通过。
- [ ] `pnpm build` 通过。

---

## 14. FE02.10：功能完成后统一补测试

只有 FE02.1～FE02.9 完成并且业务结构稳定后，才进入测试阶段。

### 统一补充的测试

- [ ] `ResearchComposer`：合法输入、trim、空输入和 disabled。
- [ ] `useResearchRun`：初始化不请求，submit 才调用 `createRun`。
- [ ] `useResearchRun`：submitting、received、request_failed、reset。
- [ ] `ResearchResponse`：四种合法 Agent 终态。
- [ ] `ResearchPage`：从输入到 Mock 结果的完整流程。
- [ ] 页面不显示原始异常、stack、API key 或 hidden reasoning。
- [ ] Route：`/research` 与 404 页面。

### 统一执行

```text
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

测试阶段只验证已经确定的功能，不借测试继续扩展 FE02 范围。

---

## 15. 推迟到后续阶段

### FE03：真实 HTTP 联调

- `POST /api/chat/runs`；
- HTTP 422；
- 非预期 HTTP 状态；
- 运行时响应校验；
- `AbortSignal` 传给 fetch；
- 根据真实交互需要决定是否加入 `requestId` 和旧响应保护。

### FE04～FE05：领域组件

- 可点击证据与来源；
- 报告期、发布时间和数据时间；
- Decision Trace；
- 组合、仓位和风险对比。

### FE06：工作流与恢复

- 后端正式取消；
- SSE 事件；
- 断线重连；
- checkpoint；
- 最终快照恢复；
- 重复事件和事件序号处理。

---

## 16. FE02 最终验收

- [x] `/research` 可以打开对话研究页面。
- [x] 用户只输入自然语言即可提交。
- [x] 空输入不会调用 Transport。
- [x] 提交时保留并显示用户消息。
- [x] 页面显示明确的加载状态。
- [x] 页面展示结构化 facts 和 inferences。
- [x] 页面展示 evidence ID、run ID 和真实 data mode。
- [x] 资料不足、Agent 失败和取消都有明确显示。
- [x] Transport 抛错时只显示统一安全错误。
- [x] 页面不暴露内部异常、密钥或模型内部信息。
- [x] 页面没有提前实现 FE03/FE06 能力。
- [x] 代码结构能够清楚说明从 Page 内实现到 Hook/组件抽离的过程。
- [ ] 功能完成后统一补充的测试全部通过。
