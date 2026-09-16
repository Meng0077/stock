# Stock Agent 前端并行开发计划

本文从 `stock-agent-python-development-plan.md` 和 `docs/week2.md` 中提取前端工作，形成一条可与后端 D08 之后任务并行推进的开发线。

当前仓库已完成 `frontend/` 工程初始化；研究请求、结果和后期领域功能仍按本文步骤逐项实现，不把尚未实现的功能标记为完成，也不提前虚构后端尚未提供的字段。

## 1. 前端目标与边界

技术栈：React + TypeScript。

最终页面负责：

- 以对话方式输入自然语言研究问题和后期的风险假设；
- 展示运行身份、状态、事实、推断、缺失信息和证据；
- 后续展示行情时间、宏观统计期、引用、不确定性和 Decision Trace；
- 后续对比当前仓位与假设调整后的风险；
- 明确分开“市场观点”和“个人风险结论”；
- 只展示后端允许公开的安全错误，不展示原始异常、密钥或内部模型信息。

### D10 最小对话版本不做

- Redux 或复杂全局状态管理；
- 图表和复杂 dashboard；
- 后端语义尚未确定的 SSE、断线重连和任务恢复；
- 真正的多轮 Agent memory、上下文压缩和历史会话恢复；
- 要求用户填写 `company_id`、`data_mode` 或 `as_of` 等内部研究字段；
- 用前端假数据冒充真实来源、实时行情或个人风险结论。

### D50 面试首版始终不做

- 下单、模拟成交或券商写权限；
- 在浏览器保存模型密钥、券商凭据或账户号；
- 展示隐藏思维链，或把临时 token 当作正式研究结果。

## 2. 从总计划提取的原始前端任务

| 原开发日 | 前端任务 | 完成标准 |
| --- | --- | --- |
| D10 | 建立 React 对话式研究页骨架 | 浏览器跑通 `自然语言 → 对话 API → 后端归一化 → Agent → Tool → ResearchOutput → React` |
| D10 | 最小对话与结果展示 | 用户只输入自然语言；页面展示用户消息、`run_id`、状态、facts、evidence ID 和 data mode；失败不泄露原始异常 |
| D43 | 完善问题输入与研究结果页 | 显示行情时间、宏观统计期、引用和不确定性 |
| D44 | 展示决策与风险 | 展示 Decision Trace、当前仓位与假设后风险；市场观点与个人风险结论清楚分开 |
| D45 | 演示状态分支 | 正常、资料不足、风险否决和取消均可演示；旧请求不能覆盖当前页面 |
| 最终验收 | 完成面试版工作台 | 页面可展示市场观点、个人风险结论、引用、数据时间和适用条件 |

## 3. 并行开发策略

前端不再等到第 9 周才整体开始，而是拆成两类：

1. **契约已经存在的功能**：现在使用固定 mock 并行开发。
2. **依赖未来领域模型的功能**：先确定组件插槽和验收条件，等后端契约落地后再接入，不预造字段。

### 前后端并行时间线

| 前端阶段 | 可并行的后端阶段 | 前端产物 | 是否等待后端 |
| --- | --- | --- | --- |
| FE01 工程与契约 | D08 Manual/LangChain 对照 | React 工程、公开对话请求类型、结构化响应类型、mock | 否 |
| FE02 最小对话页面 | D08–D09 Agent 收口 | Composer、单轮对话记录、状态机、结果和安全错误组件 | 否，先使用 mock |
| FE03 真实 API 联调 | D10 完整链路 | 对话 API 客户端和浏览器端到端测试 | 是，等待后端对话请求归一化入口 |
| FE04 证据与数据时间 | D11–D30 RAG/数据工具 | 引用、行情、宏观和新闻时间展示 | 是，等待证据和时间契约 |
| FE05 决策与风险 | D31–D40 决策/组合/风险 | Decision Trace、仓位前后对比 | 是，等待领域模型和 API |
| FE06 工作流状态 | D41–D45 LangGraph | 取消、恢复、竞态保护；可选 SSE | 部分；竞态保护可提前，真实取消/SSE 等后端 |
| FE07 交付与演示 | D46–D50 集成评估 | 可访问性、响应式、部署说明和演示路径 | 是，等待全链路稳定 |

当前应立即开始 FE01 和 FE02；D09 完成后收口 FE03。FE04–FE06 不阻塞前端基础开发。

## 4. 对话 API 与内部研究契约

对话式改造后必须区分两层请求，不能只是把前端字段改名后直接调用当前接口。

### 4.1 前端公开请求

建议新增 `POST /api/chat/runs`，避免破坏现有 `POST /api/runs` 的固定契约与后端测试。

```ts
interface CreateResearchRunRequest {
  message: string;
  conversation_id?: string;
}
```

首阶段只发送 `message`。`conversation_id` 是未来多轮会话的保留字段；在后端没有记忆语义前，前端不生成或宣传多轮上下文能力。

### 4.2 后端内部请求

当前 `POST /api/runs` 接收的 `ResearchRequest` 保留为后端教学、评估和归一化后的内部契约：

```ts
interface InternalResearchRequest {
  company_id: string;
  question: string;
  data_mode: "fixture" | "historical" | "live";
  as_of: string;
}
```

对话入口必须在服务端完成：

```text
CreateResearchRunRequest
  ↓ Request Normalizer
Internal ResearchRequest
  ↓ existing runner
RunResponse
```

- `company_id`：从消息识别；不明确时返回信息不足，不能静默猜错标的；
- `question`：保留用户原意，不能把持仓或限制条件丢掉；
- `as_of`：使用服务器带时区时间，或解析用户明确指定的历史时点；
- `data_mode`：由服务端环境和实际数据源决定，不能信任模型或浏览器自行标记；
- 工具选择：仍由 Agent 与白名单执行层负责，前端不决定。

### 4.3 公开响应

```ts
type RunStatus =
  | "completed"
  | "insufficient_information"
  | "failed"
  | "cancelled";

interface EvidenceClaim {
  text: string;
  evidence_ids: string[];
}

interface ResearchOutput {
  status: "completed" | "insufficient_information";
  facts: EvidenceClaim[];
  inferences: EvidenceClaim[];
  missing_information: string[];
  data_mode: DataMode;
}

type ErrorCode =
  | "invalid_json"
  | "invalid_output"
  | "invalid_evidence"
  | "data_mode_mismatch"
  | "incomplete_response"
  | "model_refusal"
  | "invalid_tool_call"
  | "model_timeout"
  | "model_error"
  | "tool_timeout"
  | "total_timeout"
  | "cancelled"
  | "budget_exhausted";

interface PublicError {
  code: ErrorCode;
  message: string;
  stage: "model" | "tool" | "validation" | "task";
}

type RunResponse =
  | { run_id: string; status: "completed"; result: CompletedResearchOutput; error: null }
  | { run_id: string; status: "insufficient_information"; result: InsufficientInformationResearchOutput; error: null }
  | { run_id: string; status: "failed"; result: null; error: PublicError }
  | { run_id: string; status: "cancelled"; result: null; error: PublicError };
```

页面必须遵守响应组合：

- `completed` / `insufficient_information`：有 `result`，没有 `error`；
- `failed` / `cancelled`：没有 `result`，有 `error`；
- 页面按外层 `status` 决定终态，并检查 `result.status` 与其一致；
- HTTP 422 是 FastAPI 请求校验响应，不是 `RunResponse`，需单独解析。

### 4.4 当前契约缺口与 FE03 闸门

当前后端尚未实现 `CreateResearchRunRequest → ResearchRequest` 的归一化入口。因此：

- FE01 可以先定义目标公开请求类型和 mock；
- FE02 可以通过 Fake Transport 完成对话 UI；
- FE03 真实联调必须等待后端新增对话入口及其 Pydantic 请求模型、归一化测试和安全错误映射；
- 前端不得把自然语言在浏览器中自行解析成股票代码或伪造 `data_mode/as_of`。

当前 `ResearchOutput` 只有证据 ID，没有证据来源、链接、发布时间或原文片段。因此：

- FE02 可以展示 `Evidence: E1`；
- 不能把 `E1` 擅自展示成某个网站或真实行情来源；
- D10 若要求显示完整来源，后端必须补充公开证据摘要，或提供按 `evidence_id` 查询的只读接口；
- 行情时间、宏观统计期、新闻时间、Decision Trace 和风险对比均等待后续契约。

当前 FastAPI 也没有单独配置浏览器跨域访问。FE03 联调时优先使用现有 Vite `/api` 开发代理保持同源；如果部署方式确实跨域，再由后端添加精确来源白名单，不使用任意来源配置。

## 5. FE01：创建工程与契约层

目标：建立可运行、可测试的前端项目，所有开发先依赖固定契约和 mock，不调用真实模型。

### Step FE01.1：建立 React + TypeScript 工程

- [x] 创建 `frontend/package.json`、TypeScript 和构建配置。
- [x] 创建 `frontend/src/main.tsx`、`frontend/src/App.tsx` 和 Tailwind 基础样式。
- [x] 提供 `dev`、`build`、`test`、`lint` 和 `typecheck` 命令。
- [x] 将依赖目录和前端构建产物加入 `frontend/.gitignore`。

完成标准：开发服务器能启动，生产构建成功，测试命令能执行。

完成记录：使用 pnpm 初始化 React 19 + TypeScript 6 + Vite 8 + Tailwind CSS 4；接入 Oxlint、Vitest 与 React Testing Library；配置 `/api` 到本地 FastAPI 的开发代理。`lint`、`typecheck`、`test` 和 `build` 均已通过。

### Step FE01.2：定义当前 API 类型

文件：`frontend/src/api/contracts.ts`

- [x] 定义前端公开的 `CreateResearchRunRequest`，只要求 `message`，并保留可选 `conversation_id`。
- [x] 定义 `RunResponse`、`ResearchOutput`、`EvidenceClaim`、`PublicError`。
- [x] 单独定义 FastAPI HTTP 422 的响应结构。
- [x] 不提前加入来源、行情、Decision Trace 或风险字段。

完成记录：`RunResponse` 使用可辨识联合类型表达四种终态及其合法 `result/error` 组合；公开错误码和阶段与后端固定集合一致。对话请求不暴露 `company_id/data_mode/as_of`；这些内部字段等待后端归一化入口生成并校验。

### Step FE01.3：准备固定 mock

文件：`frontend/src/mocks/runResponses.ts`

- [x] 从 `docs/d06-step7-valid-response.json` 派生成功 mock。
- [x] 准备 `insufficient_information`、`failed`、`cancelled` 和 HTTP 422 mock。
- [x] 准备只包含自然语言 `message` 的公开请求 mock；422 字段位置使用 `body.message`。
- [x] mock 明确标注为 fixture，不能展示成真实市场数据。

建议函数：

```ts
function getMockRunResponse(status: RunStatus): RunResponse;
```

输入：希望模拟的运行终态。

输出：符合当前公开契约、不可被页面意外修改的固定响应。

功能：让页面在不请求后端和模型的情况下覆盖所有状态。

完成记录：`getMockCreateResearchRunRequest()` 提供不含内部研究字段的自然语言请求；`getMockRunResponse()` 按传入状态返回精确响应类型和独立副本；`getMockValidationError()` 提供面向 `message` 的 HTTP 422 fixture。测试覆盖公开请求、四种运行终态、D06 示例关键字段、fixture 声明、副本隔离、422 结构和安全错误边界。

## 6. FE02：对话式研究页面与状态处理

目标：完成 D10 的最小对话式研究页面。

用户不需要理解或填写 `company_id`、`data_mode`、`as_of` 等内部研究字段，只需要像聊天一样描述自己的问题，例如：

> 帮我看看英伟达最近怎么样。

或：

> 我现在持有 NVDA，成本 220，最近适不适合继续加仓？

前端负责提交自然语言消息、展示研究结果和维护请求生命周期。

后端负责根据用户自然语言补充或推导研究所需的内部上下文，例如：

* 标的识别；
* 当前或用户指定的 `as_of`；
* 所需工具和数据源；
* fixture / historical / live 等实际数据模式；
* 是否需要报价、RAG、新闻、宏观或组合风险数据。

前端不得要求用户替 Agent 完成这些内部决策。

---

### Step FE02.1：对话输入组件

文件：

`frontend/src/features/research/ResearchComposer.tsx`

目标：提供类似聊天输入框的最小研究入口。

用户只输入自然语言消息。

建议前端 API 请求类型：

```ts
interface CreateResearchRunRequest {
  message: string;
  conversation_id?: string;
}
```

第一阶段可以不实现真正的多轮 conversation memory，`conversation_id` 可暂时省略或保留为可选字段。

组件接口：

```ts
interface ResearchComposerProps {
  disabled: boolean;

  onSubmit: (
    request: CreateResearchRunRequest
  ) => void | Promise<void>;
}
```

职责：

* 收集用户自然语言；
* 做最基本的空输入校验；
* 将消息交给页面控制器；
* 不直接调用 API；
* 不负责渲染研究结果；
* 不解析股票代码；
* 不决定 `data_mode`；
* 不生成 `as_of`；
* 不决定使用哪些工具。

React 19 建议使用 `<form action={...}>`：

```tsx
export function ResearchComposer({
  disabled,
  onSubmit,
}: ResearchComposerProps) {
  async function submitAction(
    formData: FormData,
  ) {
    const message = String(
      formData.get("message") ?? "",
    ).trim();

    if (!message) {
      return;
    }

    await onSubmit({
      message,
    });
  }

  return (
    <form action={submitAction}>
      <textarea
        name="message"
        placeholder="例如：帮我看看英伟达最近怎么样..."
        required
      />

      <button
        type="submit"
        disabled={disabled}
      >
        发送
      </button>
    </form>
  );
}
```

第一版可以采用 uncontrolled form，不要求为输入框单独维护 `useState`。

完成标准：

* [ ] 用户只需输入一段自然语言；
* [ ] 空消息不能提交；
* [ ] 不向用户暴露 `company_id`、`data_mode`、`as_of`；
* [ ] 提交逻辑通过 `onSubmit` 向外传递；
* [ ] 页面后续可方便替换 mock API 和真实 API。

---

### Step FE02.2：API 请求契约

文件：`frontend/src/api/contracts.ts`

FE01 已完成 `CreateResearchRunRequest` 与结构化 `RunResponse`。功能代码统一从 API 契约层导入，不在 feature 目录重复声明接口。为兼容当前学习文件，`frontend/src/features/research/type.ts` 只做类型转出，不拥有第二份定义。

后端返回继续使用可辨识联合类型：成功/信息不足一定有 `result`，失败/取消一定有安全 `error`。`ResearchOutput.data_mode` 仍是必填字段，不能因为改成对话 UI 就变成可选。

注意：

对话式 UI 不代表后端改成纯 Markdown 输出。

仍然保持：

```text
自然语言输入
    ↓
Agent
    ↓
结构化 ResearchOutput
    ↓
React 渲染成对话消息
```

而不是：

```text
自然语言输入
    ↓
LLM Markdown
    ↓
dangerouslySetInnerHTML
```

完成标准：

* [x] 前端请求模型只包含用户真正需要填写的字段；
* [x] 前端代码不声明或生成后端内部 `ResearchRequest`；
* [x] 页面依赖自己的 API contract，不依赖 LangChain Message / LangGraph State；
* [ ] D10 后端对话入口实现归一化后，验证 Manual → LangChain → LangGraph 的内部迁移无需修改前端协议。

---

### Step FE02.3：页面请求状态机

文件：

`frontend/src/features/research/useResearchRun.ts`

目标：集中处理一次研究请求的生命周期。

页面状态至少包括：

```ts
type ResearchViewState =
  | {
      kind: "idle";
    }
  | {
      kind: "submitting";
      requestId: number;
      userMessage: string;
    }
  | {
      kind: "received";
      requestId: number;
      userMessage: string;
      response: RunResponse;
    }
  | {
      kind: "request_invalid";
      userMessage: string;
      messages: string[];
    }
  | {
      kind: "request_failed";
      requestId: number;
      userMessage: string;
      errorMessage: string;
    };
```

终态继续保存 `userMessage`，否则请求完成后无法把用户气泡与对应的 Agent 结果组成一轮对话。`requestId` 是前端竞态标识，`run_id` 是后端运行身份，两者不能混用。

建议 Hook：

```ts
function useResearchRun(
  createRun: (
    request: CreateResearchRunRequest,
    signal?: AbortSignal,
  ) => Promise<RunResponse>,
): {
  state: ResearchViewState;

  submit: (
    request: CreateResearchRunRequest
  ) => Promise<void>;

  reset: () => void;
};
```

职责：

* 管理 loading；
* 管理 HTTP 请求；
* 管理 AbortController；
* 处理 HTTP 422；
* 处理断网或 HTTP transport failure；
* 防止旧请求覆盖新结果；
* 不解释 Agent 业务结果。

---

#### 请求 ID

每次提交：

```ts
const requestId =
  ++latestRequestId.current;
```

只允许最新请求更新页面：

```ts
if (
  requestId !==
  latestRequestId.current
) {
  return;
}
```

解决：

```text
请求 A
↓
请求 B
↓
B 先返回
↓
A 后返回

最终仍显示 B
```

---

#### AbortController

新请求开始时：

```ts
previousController?.abort();
```

再创建新的：

```ts
const controller =
  new AbortController();
```

调用：

```ts
await createRun(
  request,
  controller.signal,
);
```

浏览器 abort 用于停止前端等待。

后端是否真正停止 Agent，需要由 FastAPI / asyncio cancellation 单独保证。

---

#### HTTP failure 与 Agent failure 分开

以下属于：

```ts
{
  kind: "request_failed"
}
```

例如：

* 无网络；
* fetch 失败；
* 服务不可达；
* 非预期 HTTP 错误。

以下仍属于：

```ts
{
  kind: "received",
  response,
}
```

例如：

```json
{
  "status": "failed",
  "error": {
    "code": "model_timeout"
  }
}
```

因为这是：

> HTTP 请求成功，Agent 给出了合法的失败终态。

不要把：

```text
Agent failed
```

和：

```text
HTTP failed
```

混为一类。

完成标准：

* [ ] 新请求能取消旧浏览器请求；
* [ ] 旧响应无法覆盖新响应；
* [ ] transport error 与 Agent failure 分离；
* [ ] cancelled / failed RunResponse 仍作为合法业务响应处理；
* [ ] Hook 可使用 mock `createRun` 测试。

---

### Step FE02.4：对话消息展示

建议文件：

* `frontend/src/features/research/ResearchConversation.tsx`
* `frontend/src/features/research/UserMessage.tsx`
* `frontend/src/features/research/ResearchResponse.tsx`

页面视觉上采用对话结构：

```text
User

帮我看看英伟达最近怎么样，
我成本 220。

Agent

根据目前取得的资料：

事实
- ...
- ...

推断
- ...

缺失信息
- ...

数据截至：
...
```

第一阶段不实现真正多轮 Agent memory。

FE02 最小实现先保证当前一轮“用户消息 + Agent 结构化回复”完整对应。若页面保留多条本地记录，每次提交仍然对应一个独立 `run_id`，历史记录只是 UI 展示，不代表模型拥有多轮记忆。

即：

```text
message A
↓
run A

message B
↓
run B
```

而不是立即实现：

```text
完整历史上下文
↓
LLM memory
↓
conversation compression
```

这些不属于 FE02。

完成标准：

* [ ] 用户消息与 Agent 消息视觉区分；
* [ ] 请求结束后仍保留并显示该次 `userMessage`；
* [ ] 每个 Agent 结果保留自己的 `run_id`；
* [ ] 不把后端内部事件直接展示成聊天正文；
* [ ] 不把模型原始 response 直接渲染到页面。

---

### Step FE02.5：结构化研究结果组件

建议文件：

* `RunSummary.tsx`
* `ClaimList.tsx`
* `MissingInformation.tsx`
* `EvidenceBadge.tsx`
* `PublicErrorPanel.tsx`

---

#### `RunSummary`

显示：

* `run_id`
* Agent 外层状态
* 数据模式
* 后续可增加数据截至时间

例如：

```text
Run: abc-123
Status: completed
Data: fixture
```

不得把：

```text
fixture
```

包装成：

```text
实时数据
```

---

#### `ClaimList`

分开展示：

```text
Facts
```

与：

```text
Inferences
```

例如：

```text
事实

NVDA 教学模拟报价为 100 USD
[E1]
```

以及：

```text
推断

该价格不能用于实际投资判断
[E1]
```

不能合并成统一的“分析结果”，否则用户无法区分事实和系统推断。

---

#### `EvidenceBadge`

每条 claim 显示：

```text
E1
E2
```

当前阶段只需要显示 ID。

Week 3 RAG 接入后，可逐步升级成：

```text
点击 E1
↓
打开 evidence
↓
显示文档
↓
page / section / source
```

---

#### `MissingInformation`

当：

```ts
result.status ===
  "insufficient_information"
```

突出展示：

```text
缺少信息：
- 最新报价
- 当前持仓
- 某报告期资料
```

不要只显示内部状态字符串。

---

#### `PublicErrorPanel`

当：

```ts
response.status === "failed"
```

只展示：

```text
error.code
error.stage
error.message
```

不得展示：

* stack trace；
* raw exception；
* API key；
* provider headers；
* hidden reasoning；
* 原始模型请求；
* 内部路径。

---

### Step FE02.6：HTTP 422 安全格式化

建议函数：

```ts
function formatValidationMessages(
  payload: unknown,
): string[];
```

输入：

FastAPI HTTP 422 的未知 JSON。

输出：

安全、适合用户阅读的字段提示。

例如 FastAPI：

```json
{
  "detail": [
    {
      "loc": [
        "body",
        "message"
      ],
      "msg": "String should have at least 1 character"
    }
  ]
}
```

转换：

```text
message:
String should have at least 1 character
```

如果 payload 结构不是预期：

```ts
return [
  "请求参数不合法，请检查输入。"
];
```

不得：

```ts
JSON.stringify(payload)
```

直接展示未知响应全文。

完成标准：

* [ ] 只读取允许的 FastAPI validation 字段；
* [ ] 非预期 payload 使用统一错误；
* [ ] 不使用 `dangerouslySetInnerHTML` 渲染错误；
* [ ] 不显示后端原始异常全文。

---

### Step FE02.7：mock 页面测试

第一阶段尽量通过 mock API 验证 UI 与状态机，不依赖真实 LLM。

必须覆盖：

#### Case 1：自然语言提交

输入：

```text
帮我看看英伟达最近怎么样
```

应生成：

```ts
{
  message:
    "帮我看看英伟达最近怎么样"
}
```

前端不得自行生成：

```ts
company_id
data_mode
as_of
```

---

#### Case 2：completed

mock：

```ts
{
  status: "completed",
  result: {
    facts: [...],
    inferences: [...],
    missing_information: [],
  }
}
```

验证：

* [ ] 用户消息正常显示；
* [ ] facts 正确显示；
* [ ] inferences 正确显示；
* [ ] evidence IDs 正确显示；
* [ ] run_id 正确显示。

---

#### Case 3：insufficient_information

验证：

* [ ] 缺失信息明确展示；
* [ ] 页面不把缺资料结果表现为成功研究结论。

---

#### Case 4：Agent failed

例如：

```ts
{
  status: "failed",
  error: {
    code: "model_timeout",
    stage: "model",
    message: "模型请求超时。",
  },
}
```

验证：

* [ ] 当作合法 RunResponse；
* [ ] 展示 PublicError；
* [ ] 不读取 `result.facts`。

---

#### Case 5：cancelled

验证：

* [ ] 不读取 `result`；
* [ ] 页面能明确显示任务已取消。

---

#### Case 6：HTTP 422

验证：

* [ ] 进入 `request_invalid`；
* [ ] 显示安全字段提示；
* [ ] 不显示原始 JSON。

---

#### Case 7：Network failure

验证：

```ts
{
  kind: "request_failed"
}
```

与 Agent failure 不混淆。

---

#### Case 8：旧响应覆盖

模拟：

```text
request A
↓
request B
↓
B resolve
↓
A resolve
```

最终必须显示 B。

---

#### Case 9：敏感信息

mock 错误中故意加入：

```text
stack
api_key
authorization
raw_exception
reasoning_content
```

验证页面均不显示。

---

## FE02 最终数据流

```text
ResearchComposer
      ↓
用户自然语言
      ↓
CreateResearchRunRequest
      ↓
useResearchRun
      ↓
requestId / AbortController
      ↓
POST /api/chat/runs
      ↓
FastAPI
      ↓
后端 Request Normalizer
      ↓
内部 ResearchRequest
      ↓
Agent
      ↓
Tools / RAG / Data
      ↓
ResearchOutput
      ↓
RunResponse
      ↓
useResearchRun
      ↓
ResearchConversation
      ↓
结构化对话卡片
```

前端只处理：

```text
用户说了什么
请求当前处于什么状态
Agent 返回了什么结构化结果
如何安全展示
```

前端不负责：

```text
识别 NVDA
决定调用哪个工具
决定 data_mode
计算 as_of
决定需要报价还是 RAG
决定是否读取新闻
```

这些属于后端 Agent。

---

## FE02 完成标准

完成 FE02 后，应能够演示：

```text
用户：

“帮我看看英伟达最近怎么样”

↓ 点击发送

页面：

用户消息立即出现在对话区域

↓ Agent 请求

页面显示 submitting

↓ 后端返回

Agent：

事实
- ...

推断
- ...

缺失信息
- ...

证据
[E1] [E2]

Run ID
xxx
```

同时：

* [ ] 新请求不会被旧响应覆盖；
* [ ] 网络错误和 Agent 错误明确区分；
* [ ] Agent 的结构化输出没有被降级成不可验证的纯 Markdown；
* [ ] fixture / historical / live 不被错误包装；
* [ ] 页面不暴露原始异常、密钥和模型内部信息。

---

## 后续演进

FE02 只建立对话框架。

后续按开发周逐步增强：

```text
Week 3
Evidence ID
→ 可点击 RAG 原文片段

Week 5
→ 最新报价 / Bar / 数据时间

Week 6
→ 新闻来源和事件证据

Week 7
→ Decision Trace

Week 8
→ Portfolio / Risk / Scenario

Week 9
→ 完整 Research Workspace
→ 多模块整合
→ 条件分支
→ cancellation / checkpoint 展示
```

因此 FE02 不需要提前实现这些领域 UI，只需要保证当前组件结构能容纳它们。


## 7. FE03：接入真实 API

目标：在 D09 完成后跑通 D10 的浏览器完整链路。

文件：`frontend/src/api/createRun.ts`

```ts
async function createRun(
  request: CreateResearchRunRequest,
  signal?: AbortSignal,
): Promise<RunResponse>;
```

输入：用户自然语言请求和可选的浏览器取消信号。

输出：后端公开的 `RunResponse`。

功能：发送 `POST /api/chat/runs`，解析正常响应、HTTP 422 和不可用响应；不包含页面渲染逻辑。

- [ ] 等待后端实现对话入口和 Request Normalizer，不直接把 `message` 发给当前 `/api/runs`。
- [ ] 通过开发代理或部署配置使用 `/api/chat/runs`，不把地址散落在组件中。
- [ ] 请求头只声明 JSON，不在浏览器保存模型密钥。
- [ ] 区分 HTTP/网络失败、HTTP 422 和 Agent 安全终态。
- [ ] 验证响应中的 `run_id` 与当前页面结果绑定。
- [ ] 跑通 completed、insufficient information 和安全失败路径。
- [ ] 在浏览器确认旧响应保护有效。

完成标准：能现场说明一次自然语言消息如何在后端归一化，再经过 Agent、只读工具和结构化结果回到对话页面。

## 8. FE04：引用与数据时间工作台

这部分跟随 D11–D30，不提前实现虚构字段。

- [ ] D11–D14 契约落地后展示文档来源、报告期、发布时间、页码/片段位置和可打开引用。
- [ ] D21–D25 契约落地后展示报价时间、接收时间、数据延迟和日线区间。
- [ ] 展示 CPI/PPI 的统计期与发布时间，不只显示抓取时间。
- [ ] D26–D30 契约落地后展示新闻来源、事件时间、发布时间和冲突状态。
- [ ] 对过期、缺失、未来发布或冲突资料使用明确状态，不用颜色代替文字说明。

后端闸门：证据对象必须提供稳定 ID、来源、时间和定位信息；前端不从模型自然语言中猜这些字段。

## 9. FE05：Decision Trace 与风险对比

这部分跟随 D31–D40。

- [ ] 展示确定性因子、输入值、阈值、规则结果和规则版本。
- [ ] 单独显示市场观点及其证据，不称规则分数为获利概率。
- [ ] 展示当前组合市值、现金占比和单股集中度。
- [ ] 对比用户指定金额调整前后的仓位与触发规则。
- [ ] 个人资料不足时，只显示一般研究观点和无法个人化的原因。
- [ ] 风险否决与模型解释冲突时，以结构化风险结论为准并显示异常状态。

页面结构必须保持：

```text
市场研究与观点
  ├─ 证据与数据时间
  └─ Decision Trace

个人风险结论
  ├─ 当前仓位
  ├─ 假设后仓位
  └─ 触发的用户约束
```

## 10. FE06：工作流状态、取消与可选 SSE

这部分跟随 D41–D45。

- [ ] 接入后端正式取消接口，而不是只中止浏览器等待。
- [ ] 演示正常、资料不足、风险否决和取消四条路径。
- [ ] 页面状态必须与最终结果快照一致。
- [ ] 若加入恢复，显示恢复自哪个 checkpoint，并说明哪些节点会重跑。

只有后端先定义以下契约，才实施 SSE：

- `run_id` 与单调递增事件序号；
- 持久状态事件与临时 token 的区别；
- 取消后的确定终态；
- 重连起点、重复事件处理和最终结果快照；
- 页面切换请求后的旧连接关闭方式。

断线后以最终快照恢复，不能把不完整 token 拼成 `ResearchOutput`。

## 11. FE07：测试、部署与面试演示

- [ ] 组件测试覆盖各终态、空列表、长文本和无效响应。
- [ ] 浏览器端到端测试覆盖正常、资料不足、风险否决、取消和旧响应竞态。
- [ ] 键盘可操作，状态变化有文字提示，颜色不是唯一信息来源。
- [ ] 小屏和桌面宽度均可阅读证据与风险对比。
- [ ] 从干净环境可安装、构建和启动。
- [ ] README 记录前端启动、后端代理、fixture 与真实模式边界。
- [ ] 5～8 分钟演示从提问开始，经过证据和数据时间，最终展示市场观点与个人风险结论。

## 12. 建议目录（按步骤创建，不预建空文件）

```text
frontend/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/
│   │   ├── contracts.ts
│   │   └── createRun.ts
│   ├── features/research/
│   │   ├── ResearchComposer.tsx
│   │   ├── ResearchConversation.tsx
│   │   ├── UserMessage.tsx
│   │   ├── ResearchResponse.tsx
│   │   ├── RunSummary.tsx
│   │   ├── ClaimList.tsx
│   │   ├── EvidenceBadge.tsx
│   │   ├── MissingInformation.tsx
│   │   ├── PublicErrorPanel.tsx
│   │   ├── type.ts
│   │   └── useResearchRun.ts
│   ├── mocks/
│   │   └── runResponses.ts
│   └── test/
│       └── setup.ts
└── README.md
```

后期仅在对应后端契约完成时增加 `evidence/`、`decision/`、`portfolio/`、`risk/` 和 `workflow/` 功能目录。

## 13. 当前执行顺序

```text
后端：D08 ───── D09 ───── D10 ───── D11～D40 ───── D41～D45
       │          │         │            │               │
前端：FE01 ──── FE02 ──── FE03 ───── FE04/FE05 ─────── FE06
                                                        │
                                                     FE07
```

当前下一步：

1. FE01 已按对话目标修订：公开请求只含 `message` 和保留的 `conversation_id`，结构化响应保持不变。
2. 继续做 FE02，先用 Fake Transport 完成单轮对话状态和组件测试，不等待真实接口。
3. D10 前由后端增加 `/api/chat/runs` 与 Request Normalizer，再做 FE03 联调；不能直接破坏现有 `/api/runs` 契约。
4. 每次后端新增领域契约时，先补契约样例和类型，再开发对应 UI。

## 14. `ai-chat-n` 可借鉴的技术设计

`ai-chat-n/` 是参考实现，不作为 Stock Agent 的直接依赖。Stock Agent 只复用适合当前业务的设计思想，重新按自己的 API 契约和测试要求实现。

### 14.1 传输、事件处理与渲染分层

`ai-chat-n` 将流式请求、事件排队、消息格式化和内容渲染拆成不同模块。Stock Agent 后期采用类似边界：

```text
RunTransport
  ↓ 原始 HTTP / SSE 数据
RunEventParser
  ↓ 类型化 RunEvent
runReducer
  ↓ 可验证的 RunViewState
ResultRenderer
  ↓
Evidence / Decision / Risk / Error 组件
```

对应计划：

- [x] FE01：定义 `CreateResearchRunRequest` 与 `RunResponse` 等同步契约。
- [ ] FE03：通过 `RunTransport` 隔离 mock 与真实 HTTP。
- [ ] FE06：只有后端事件协议稳定后，再增加 `SseRunTransport`、事件解析器和 reducer。
- [ ] 解析和状态归并使用纯函数测试，不依赖真实模型响应。

建议接口：

```ts
interface RunTransport {
  createRun(
    request: CreateResearchRunRequest,
    options?: { signal?: AbortSignal },
  ): Promise<RunResponse>;
}
```

输入：研究请求和浏览器取消信号。

输出：经过公开契约校验的运行结果。

功能：页面只依赖统一接口；mock、普通 HTTP 和未来 SSE 的实现不会侵入组件。

### 14.2 类型驱动的内容渲染

参考 `ai-chat-n` 按消息类型选择 Text、Card、MCP 等组件的方式，Stock Agent 按领域结果类型拆分组件：

```ts
type ResultBlock =
  | { kind: "fact"; claim: EvidenceClaim }
  | { kind: "inference"; claim: EvidenceClaim }
  | { kind: "missing_information"; text: string }
  | { kind: "evidence"; evidence: EvidenceSummary }
  | { kind: "decision"; trace: DecisionTrace }
  | { kind: "risk"; assessment: RiskAssessment };
```

- [ ] 使用可辨识联合类型，避免组件通过大量可选字段猜测内容类型。
- [ ] 每种 `kind` 对应独立组件和空状态。
- [ ] 新增类型时由 TypeScript 的穷尽检查提示缺少渲染分支。
- [ ] facts 与 inferences 永远使用不同标题和视觉标识。

这比把所有 Agent 输出拼成一段 Markdown 更适合 Stock Agent，因为证据、时间和风险结论需要结构化校验。

### 14.3 取消、会话身份与旧响应隔离

参考 `ai-chat-n` 使用 `AbortController` 停止流式请求、重置会话状态的思路，Stock Agent 要同时处理两层取消：

1. 浏览器取消：用户发起新请求或离开页面时，停止等待旧连接。
2. Agent 取消：后端真正把任务进入 `cancelled` 终态。

- [ ] FE02：用本地递增 `requestId` 防止旧响应覆盖新页面。
- [ ] FE03：把 `AbortSignal` 传给请求层。
- [ ] FE06：用后端 `run_id` 关联取消、事件和最终快照。
- [ ] 浏览器 `abort()` 不得被描述为后端任务已经取消。
- [ ] 组件卸载后清理连接、定时器、监听器和回调。

### 14.4 流式事件队列与平滑输出

`ai-chat-n` 通过事件队列保证不同类型的 SSE 内容按顺序处理，并通过缓冲区控制文本显示速度。Stock Agent 仅在 FE06 可选 SSE 阶段借鉴：

- [ ] 网络到达顺序与页面提交顺序分离，通过 `seq` 验证事件顺序。
- [ ] 临时 token 可以进入显示缓冲区；状态、证据和最终结果直接按结构化事件处理。
- [ ] 缓冲区积压时允许加快渲染，但不得丢字符或改变事件顺序。
- [ ] 最终 `RunResponse` 快照是权威结果，不从屏幕上的临时文本反推结果。
- [ ] 取消、失败、结束是不同终态，不能全部归为“停止加载”。

建议函数：

```ts
function reduceRunEvent(state: RunStreamState, event: RunEvent): RunStreamState;
```

输入：当前流状态和一个已经校验的事件。

输出：新的不可变状态。

功能：确定性归并事件、拒绝错误 `run_id`、忽略重复序号，并处理完成、失败和取消终态。

### 14.5 安全 Markdown 与引用链接

`ai-chat-n` 使用 Marked 解析 Markdown，并在插入 HTML 前使用 DOMPurify 清洗。Stock Agent 只有在确实需要渲染模型说明文本时采用这条链路：

- [ ] facts、evidence、Decision Trace 和 RiskAssessment 优先按结构化字段渲染，不经过 Markdown。
- [ ] 模型解释若允许 Markdown，必须先解析、再清洗、最后渲染。
- [ ] 对链接协议、图片来源、事件属性和新窗口行为设置白名单。
- [ ] 引用链接只能来自后端验证过的 Evidence 元数据，不能信任模型生成 URL。
- [ ] 测试 `javascript:`、事件属性、恶意图片和未闭合流式标签。
- [ ] DOMPurify 是降低 XSS 风险的一层措施，简历中不写成“彻底杜绝 XSS”。

### 14.6 智能滚动与长内容体验

参考 `ai-chat-n` 的滚动管理设计，但只在页面演进为连续运行记录或流式时间线时启用：

- [ ] 用户位于底部附近时自动跟随新内容。
- [ ] 用户主动向上阅读证据时停止抢占滚动位置。
- [ ] 显示“回到最新结果”按钮。
- [ ] 使用 `requestAnimationFrame` 合并布局后的滚动更新。
- [ ] 长证据列表优先分页或折叠；达到真实性能瓶颈后再考虑虚拟列表。

### 14.7 前端可观测性

参考 `ai-chat-n` 把日志能力集中管理的设计，Stock Agent 建立不含敏感数据的前端观测事件：

- [ ] 记录 `run_id`、数据模式、公开终态和前端阶段。
- [ ] 可记录提交到首个状态、提交到最终结果的耗时。
- [ ] 记录 HTTP 失败、响应契约失败、SSE 断开和重连次数。
- [ ] 不记录问题全文、模型密钥、组合账户号、原始异常或隐藏思维链。
- [ ] 指标提升必须经过基线测量后再写简历，不预填百分比。

### 14.8 测试策略不能照搬

当前 `ai-chat-n` 目录有大量调试和模拟数据，但没有检出常规自动化测试目录。因此 Stock Agent 只参考其设计，不继承测试现状：

- [ ] 用 Vitest 测试解析器、reducer、状态组合和格式化纯函数。
- [ ] 用 React Testing Library 测试各终态和用户交互。
- [ ] 用可控 Fake Transport 测试乱序、重复、延迟、取消和断线。
- [ ] 用浏览器端到端测试覆盖输入、结果、引用和风险路径。
- [ ] 测试中固定事件与快照，不依赖真实大模型的随机回答。

## 15. 明确不从 `ai-chat-n` 搬入的内容

- Taro、H5 客户端 Bridge 和多端 Driver：Stock Agent 首版是普通 Web 页面。
- 地图、房源、定位、推荐房源和 CMS 卡片：与股票研究领域无关。
- 把模型隐藏思维过程展示给用户：Stock Agent 只展示允许公开的进度、工具结果和 Decision Trace。
- 巨型消息对象与大量 `any`：新项目应使用小型领域对象和严格类型。
- 在后端协议确定前先做 SSE：仍遵守 FE06 的接口闸门。

## 16. 简历能力与验收项对应关系

| 简历可表达能力 | 必须完成的代码与验证 | 最早可写入时间 |
| --- | --- | --- |
| React + TypeScript 结构化 Agent 工作台 | FE01/FE02 页面、类型、组件测试 | FE02 验收后 |
| mock/HTTP/SSE 传输解耦 | `RunTransport`、Fake Transport 和接口测试 | FE03；SSE 只能在 FE06 后写 |
| 防止旧结果污染当前会话 | `AbortController`、requestId/run_id 校验、竞态测试 | FE03 验收后 |
| 安全 Markdown 和可信引用 | Marked/DOMPurify、URL 白名单、XSS 用例 | FE04 验收后 |
| 类型化流式事件与恢复 | `RunEvent`、序号、reducer、最终快照和断线测试 | FE06 验收后 |
| Decision Trace 与个性化风险对比 | 决策/风险组件及完整 E2E | FE05/FE07 验收后 |

简历表述草稿与真实性边界见 `docs/frontend-resume-notes.md`。
