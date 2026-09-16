# FE02 TODO：对话式研究页面与状态处理

> 对应总计划：`docs/frontend-development-plan.md` 的“FE02：对话式研究页面与状态处理”。

## 1. 本阶段目标

完成一个基于 Mock Transport 的单轮对话研究页面：

```text
用户输入自然语言
    ↓
页面立即显示用户消息和提交状态
    ↓
Mock createRun 返回结构化 RunResponse
    ↓
页面分别展示事实、推断、证据、缺失信息或安全错误
```

FE02 不依赖真实 LLM，也不等待后端 `/api/chat/runs` 完成。

## 2. 当前进度

- [ ] FE02.1 对话输入组件：已有初版，仍需修正和测试。
- [x] FE02.2 API 请求契约：FE01 已完成。
- [ ] FE02.3 页面请求状态机：只有类型骨架，尚未实现。
- [ ] FE02.4 对话消息展示：尚未实现。
- [ ] FE02.5 结构化研究结果组件：尚未实现。
- [ ] FE02.6 HTTP 422 安全格式化：尚未实现。
- [ ] FE02.7 Mock 页面测试：尚未实现。

---

## 3. FE02.1：完成对话输入组件

文件：

```text
frontend/src/features/research/ResearchComposer.tsx
frontend/src/features/research/ResearchComposer.test.tsx
```

组件接口：

```ts
interface ResearchComposerProps {
  disabled: boolean
  onSubmit: (
    request: CreateResearchRunRequest,
  ) => void | Promise<void>
}
```

TODO：

- [ ] 从 `frontend/src/api/contracts.ts` 导入 `CreateResearchRunRequest`。
- [ ] 删除组件内重复声明的 `CreateResearchRunRequest`。
- [ ] 删除未使用的 `React` 导入。
- [ ] 读取 `message` 并执行 `trim()`。
- [ ] 空字符串或纯空格不能调用 `onSubmit`。
- [ ] 合法输入只提交 `{ message }`。
- [ ] `disabled=true` 时禁用发送按钮。
- [ ] 不显示或生成 `company_id`、`data_mode`、`as_of`。
- [ ] 添加输入框的可访问名称，确保测试可以稳定查找。
- [ ] 测试合法提交、空输入、去除首尾空格和禁用状态。

完成标准：

```ts
onSubmit({
  message: "帮我看看英伟达最近怎么样",
})
```

---

## 4. FE02.2：使用统一 API 请求契约

文件：

```text
frontend/src/api/contracts.ts
frontend/src/features/research/type.ts
```

当前契约：

```ts
interface CreateResearchRunRequest {
  message: string
  conversation_id?: string
}
```

TODO：

- [x] 请求类型集中定义在 API 契约层。
- [x] feature 层的 `type.ts` 只转出类型，不维护第二份定义。
- [x] `RunResponse` 保持可辨识联合类型。
- [x] `ResearchOutput.data_mode` 保持必填。
- [ ] D10 后端对话入口完成后，验证真实请求协议；该项不阻塞 FE02。

---

## 5. FE02.3：实现页面请求状态机

文件：

```text
frontend/src/features/research/useResearchRun.ts
frontend/src/features/research/useResearchRun.test.ts
```

状态类型：

```ts
type ResearchViewState =
  | {
      kind: "idle"
    }
  | {
      kind: "submitting"
      requestId: number
      userMessage: string
    }
  | {
      kind: "received"
      requestId: number
      userMessage: string
      response: RunResponse
    }
  | {
      kind: "request_invalid"
      userMessage: string
      messages: string[]
    }
  | {
      kind: "request_failed"
      requestId: number
      userMessage: string
      errorMessage: string
    }
```

Hook 接口：

```ts
function useResearchRun(
  createRun: (
    request: CreateResearchRunRequest,
    signal?: AbortSignal,
  ) => Promise<RunResponse>,
): {
  state: ResearchViewState
  submit: (
    request: CreateResearchRunRequest,
  ) => Promise<void>
  reset: () => void
}
```

TODO：

- [ ] 使用 `useState` 保存 `ResearchViewState`。
- [ ] 使用 `useRef` 保存最新的递增 `requestId`。
- [ ] 使用 `useRef` 保存当前 `AbortController`。
- [ ] 每次提交前取消上一个浏览器请求。
- [ ] 提交开始时进入 `submitting`。
- [ ] 请求成功时进入 `received`。
- [ ] HTTP 422 进入 `request_invalid`。
- [ ] 网络、服务不可达或其他 transport error 进入 `request_failed`。
- [ ] 只有最新 `requestId` 可以更新页面状态。
- [ ] `reset()` 取消当前请求并恢复 `idle`。
- [ ] Hook 卸载时取消仍在执行的请求。
- [ ] Abort 产生的旧请求错误不能覆盖新请求状态。
- [ ] Agent 的 `failed` 和 `cancelled` 响应仍作为合法 `received` 状态处理。

必须保持以下边界：

```text
HTTP/网络失败
→ request_failed

HTTP 成功，但 Agent 返回 failed/cancelled
→ received
```

测试：

- [ ] 首次提交状态变化正确。
- [ ] 新请求会取消旧请求。
- [ ] A 后返回、B 先返回时最终显示 B。
- [ ] transport error 和 Agent failure 不混淆。
- [ ] reset 后恢复 idle。

---

## 6. FE02.4：实现对话消息展示

建议文件：

```text
frontend/src/features/research/ResearchConversation.tsx
frontend/src/features/research/UserMessage.tsx
frontend/src/features/research/ResearchResponse.tsx
```

建议接口：

```ts
interface UserMessageProps {
  message: string
}

interface ResearchResponseProps {
  response: RunResponse
}

interface ResearchConversationProps {
  state: ResearchViewState
}
```

TODO：

- [ ] 用户消息和 Agent 消息使用不同的视觉样式。
- [ ] `submitting` 时立即显示用户消息。
- [ ] `submitting` 时显示明确的加载状态。
- [ ] 请求完成后继续保留本轮 `userMessage`。
- [ ] 将 `RunResponse` 交给结构化结果组件渲染。
- [ ] 每个 Agent 结果显示自己的 `run_id`。
- [ ] 不把后端内部事件展示成聊天正文。
- [ ] 不直接渲染模型原始 response。
- [ ] 不暗示页面已经拥有真正的多轮模型记忆。

FE02 的最小会话关系：

```text
message A → run A
message B → run B
```

本地保留历史消息只表示 UI 历史，不表示模型自动获得历史上下文。

---

## 7. FE02.5：实现结构化研究结果组件

建议文件：

```text
frontend/src/features/research/RunSummary.tsx
frontend/src/features/research/ClaimList.tsx
frontend/src/features/research/MissingInformation.tsx
frontend/src/features/research/EvidenceBadge.tsx
frontend/src/features/research/PublicErrorPanel.tsx
```

建议接口：

```ts
interface RunSummaryProps {
  response: RunResponse
}

interface ClaimListProps {
  title: string
  claims: readonly Claim[]
}

interface MissingInformationProps {
  items: readonly string[]
}

interface EvidenceBadgeProps {
  evidenceId: string
}

interface PublicErrorPanelProps {
  error: PublicError
}
```

具体类型名称以 `frontend/src/api/contracts.ts` 中的现有导出为准，不在组件文件中复制领域类型。

TODO：

- [ ] `RunSummary` 展示 `run_id`、状态和真实 `data_mode`。
- [ ] 不把 fixture 数据描述成实时数据。
- [ ] `ClaimList` 分开渲染 facts 与 inferences。
- [ ] 每条 claim 显示关联的 evidence ID。
- [ ] `EvidenceBadge` 当前只显示 ID，不提前实现证据详情弹窗。
- [ ] `insufficient_information` 突出显示缺失信息。
- [ ] `failed` 只展示 `error.code`、`error.stage`、`error.message`。
- [ ] `cancelled` 明确显示任务已取消。
- [ ] 按 `response.status` 缩小类型后再读取 `result` 或 `error`。
- [ ] 不显示 stack、raw exception、API key、provider headers、内部路径或 hidden reasoning。

---

## 8. FE02.6：实现 HTTP 422 安全格式化

建议文件：

```text
frontend/src/features/research/formatValidationMessages.ts
frontend/src/features/research/formatValidationMessages.test.ts
```

函数接口：

```ts
function formatValidationMessages(
  payload: unknown,
): string[]
```

功能：

将未知的 FastAPI HTTP 422 JSON 转换成可以安全展示给用户的字段提示。

TODO：

- [ ] 将输入始终视为 `unknown`，先检查再读取。
- [ ] 只读取允许的 `detail[].loc` 和 `detail[].msg`。
- [ ] 将合法错误转换为 `字段: 错误信息`。
- [ ] 非预期结构返回 `请求参数不合法，请检查输入。`。
- [ ] 不直接向用户展示 `JSON.stringify(payload)`。
- [ ] 不使用 `dangerouslySetInnerHTML`。
- [ ] 不展示后端原始异常全文。
- [ ] 测试标准 422、空对象、数组、字符串、恶意额外字段和字段缺失。

---

## 9. FE02.7：组装 Mock 页面并完成测试

建议文件：

```text
frontend/src/features/research/ResearchPage.tsx
frontend/src/features/research/ResearchPage.test.tsx
frontend/src/App.tsx
```

TODO：

- [ ] 创建可控制成功、失败、延迟和乱序响应的 Fake `createRun`。
- [ ] 使用 `useResearchRun(createRun)` 管理页面状态。
- [ ] 连接 `ResearchComposer` 和 `submit`。
- [ ] 连接 `ResearchConversation` 和当前状态。
- [ ] 使用研究页面替换当前 App 初始化占位内容。
- [ ] 保持 Mock Transport 可被 FE03 的 HTTP Transport 替换。

必须覆盖以下用例：

- [ ] 自然语言输入只提交 `{ message }`。
- [ ] `completed` 显示用户消息、facts、inferences、evidence ID 和 `run_id`。
- [ ] `insufficient_information` 明确显示缺失信息。
- [ ] Agent `failed` 被当作合法 `RunResponse` 并显示安全错误。
- [ ] `cancelled` 不读取 `result`，并显示取消状态。
- [ ] HTTP 422 进入 `request_invalid`，不显示原始 JSON。
- [ ] Network failure 进入 `request_failed`，不与 Agent failure 混淆。
- [ ] A、B 请求乱序返回时最终只显示 B。
- [ ] 页面不显示 `stack`、`api_key`、`authorization`、`raw_exception` 或 `reasoning_content`。

---

## 10. FE02 不做的内容

- [ ] 不在 FE02 调用真实 `/api/chat/runs`；真实 HTTP 接入属于 FE03。
- [ ] 不在浏览器中识别股票代码。
- [ ] 不由前端选择 Agent 工具。
- [ ] 不由前端生成 `as_of`。
- [ ] 不由前端决定 `data_mode`。
- [ ] 不实现真正的多轮 Agent memory。
- [ ] 不实现 SSE 流式事件。
- [ ] 不实现 Markdown/HTML 富文本渲染。
- [ ] 不实现可点击的 RAG 证据详情。
- [ ] 不实现新闻、组合风险或 Decision Trace 页面。

以上条目用于明确范围，不需要勾选为“已实现”。

---

## 11. 推荐实施顺序

```text
FE02.1 ResearchComposer
    ↓
FE02.3 useResearchRun
    ↓
FE02.6 formatValidationMessages
    ↓
FE02.5 结构化结果组件
    ↓
FE02.4 对话消息与页面组装
    ↓
FE02.7 Mock 集成测试
```

## 12. FE02 总体验收

- [ ] 用户只输入自然语言即可发起研究。
- [ ] 用户消息在提交后立即显示。
- [ ] 页面明确显示提交中状态。
- [ ] 页面使用结构化组件展示 facts、inferences、evidence 和 missing information。
- [ ] 页面显示正确的 `run_id` 和 `data_mode`。
- [ ] 新请求不会被旧响应覆盖。
- [ ] 网络错误和 Agent 错误明确区分。
- [ ] Agent 输出没有被降级为不可验证的纯 Markdown。
- [ ] 页面不暴露原始异常、密钥或模型内部信息。
- [ ] FE02 的组件和状态测试全部通过。
- [ ] TypeScript 类型检查通过。
- [ ] lint 检查通过。
- [ ] 前端测试全部通过。
