# Stock Agent 前端并行开发计划

本文从 `stock-agent-python-development-plan.md` 和 `docs/week2.md` 中提取前端工作，形成一条可与后端 D08 之后任务并行推进的开发线。

当前仓库已完成 `frontend/` 工程初始化；研究请求、结果和后期领域功能仍按本文步骤逐项实现，不把尚未实现的功能标记为完成，也不提前虚构后端尚未提供的字段。

## 1. 前端目标与边界

技术栈：React + TypeScript。

最终页面负责：

- 输入公司、研究问题、资料模式、研究截止时间和后期的风险假设；
- 展示运行身份、状态、事实、推断、缺失信息和证据；
- 后续展示行情时间、宏观统计期、引用、不确定性和 Decision Trace；
- 后续对比当前仓位与假设调整后的风险；
- 明确分开“市场观点”和“个人风险结论”；
- 只展示后端允许公开的安全错误，不展示原始异常、密钥或内部模型信息。

首版不做：

- Redux 或复杂全局状态管理；
- 图表和复杂 dashboard；
- 下单、模拟成交或券商写权限；
- 后端语义尚未确定的 SSE、断线重连和任务恢复；
- 用前端假数据冒充真实来源、实时行情或个人风险结论。

## 2. 从总计划提取的原始前端任务

| 原开发日 | 前端任务 | 完成标准 |
| --- | --- | --- |
| D10 | 建立 React 结果页骨架 | 浏览器跑通 `React → POST /api/runs → FastAPI → Agent → Tool → ResearchOutput → React` |
| D10 | 最小请求与结果展示 | 可输入请求，展示 `run_id`、状态、facts、evidence ID 和 data mode；失败不泄露原始异常 |
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
| FE01 工程与契约 | D08 Manual/LangChain 对照 | React 工程、TypeScript 类型、mock | 否 |
| FE02 最小交互页面 | D08–D09 Agent 收口 | 表单、状态机、结果和安全错误组件 | 否 |
| FE03 真实 API 联调 | D10 完整链路 | `POST /api/runs` 客户端和浏览器端到端测试 | 是，等待 D09/D10 最终 runner 与本地访问方式 |
| FE04 证据与数据时间 | D11–D30 RAG/数据工具 | 引用、行情、宏观和新闻时间展示 | 是，等待证据和时间契约 |
| FE05 决策与风险 | D31–D40 决策/组合/风险 | Decision Trace、仓位前后对比 | 是，等待领域模型和 API |
| FE06 工作流状态 | D41–D45 LangGraph | 取消、恢复、竞态保护；可选 SSE | 部分；竞态保护可提前，真实取消/SSE 等后端 |
| FE07 交付与演示 | D46–D50 集成评估 | 可访问性、响应式、部署说明和演示路径 | 是，等待全链路稳定 |

当前应立即开始 FE01 和 FE02；D09 完成后收口 FE03。FE04–FE06 不阻塞前端基础开发。

## 4. 当前公开 API 契约

### 请求

`POST /api/runs`

```ts
type DataMode = "fixture" | "historical" | "live";

interface ResearchRequest {
  company_id: string; // 1～80 个字符
  question: string;   // 1～2000 个字符
  data_mode: DataMode;
  as_of: string;      // 必须是带时区的 ISO 8601 时间
}
```

### 响应

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

interface RunResponse {
  run_id: string;
  status: RunStatus;
  result: ResearchOutput | null;
  error: PublicError | null;
}
```

页面必须遵守响应组合：

- `completed` / `insufficient_information`：有 `result`，没有 `error`；
- `failed` / `cancelled`：没有 `result`，有 `error`；
- 页面按外层 `status` 决定终态，并检查 `result.status` 与其一致；
- HTTP 422 是 FastAPI 请求校验响应，不是 `RunResponse`，需单独解析。

### 当前契约缺口

当前 `ResearchOutput` 只有证据 ID，没有证据来源、链接、发布时间或原文片段。因此：

- FE02 可以展示 `Evidence: E1`；
- 不能把 `E1` 擅自展示成某个网站或真实行情来源；
- D10 若要求显示完整来源，后端必须补充公开证据摘要，或提供按 `evidence_id` 查询的只读接口；
- 行情时间、宏观统计期、新闻时间、Decision Trace 和风险对比均等待后续契约。

当前 FastAPI 也没有单独配置浏览器跨域访问。FE03 联调时优先使用前端开发代理保持同源；如果部署方式确实跨域，再由后端添加精确来源白名单，不使用任意来源配置。

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

- [x] 定义本节列出的 `ResearchRequest`、`RunResponse`、`ResearchOutput`、`EvidenceClaim`、`PublicError`。
- [x] 单独定义 FastAPI HTTP 422 的响应结构。
- [x] 不提前加入来源、行情、Decision Trace 或风险字段。

完成记录：`RunResponse` 使用可辨识联合类型表达四种终态及其合法 `result/error` 组合；公开错误码和阶段与后端固定集合一致。字符串长度与 `as_of` 时区属于运行时规则，仍由 FastAPI 最终校验。

### Step FE01.3：准备固定 mock

文件：`frontend/src/mocks/runResponses.ts`

- [x] 从 `docs/d06-step7-valid-response.json` 派生成功 mock。
- [x] 准备 `insufficient_information`、`failed`、`cancelled` 和 HTTP 422 mock。
- [x] mock 明确标注为 fixture，不能展示成真实市场数据。

建议函数：

```ts
function getMockRunResponse(status: RunStatus): RunResponse;
```

输入：希望模拟的运行终态。

输出：符合当前公开契约、不可被页面意外修改的固定响应。

功能：让页面在不请求后端和模型的情况下覆盖所有状态。

完成记录：`getMockRunResponse()` 按传入状态返回精确响应类型和独立副本；`getMockValidationError()` 提供 HTTP 422 fixture。测试覆盖四种运行终态、D06 示例关键字段、fixture 声明、副本隔离、422 结构和安全错误边界。FE01 完成时前端共 12 个测试通过。

## 6. FE02：最小页面与状态处理

目标：完成 D10 页面主体，并提前解决 D45 的旧响应覆盖问题。

### Step FE02.1：请求表单

文件：`frontend/src/features/research/ResearchForm.tsx`

- [ ] 输入 `company_id`、`question`、`data_mode` 和 `as_of`。
- [ ] 提交中禁用重复提交或明确允许新请求替换旧请求。
- [ ] 浏览器侧只做方便用户的基础校验；后端仍是最终校验者。
- [ ] `as_of` 提交前转换为带时区的 ISO 8601 字符串。

组件输入输出：

```ts
interface ResearchFormProps {
  disabled: boolean;
  onSubmit: (request: ResearchRequest) => void | Promise<void>;
}
```

功能：收集请求并交给页面控制器，不直接负责渲染结果。

### Step FE02.2：页面状态机

文件：`frontend/src/features/research/useResearchRun.ts`

页面状态至少包括：

```ts
type ResearchViewState =
  | { kind: "idle" }
  | { kind: "submitting"; requestId: number }
  | { kind: "received"; response: RunResponse }
  | { kind: "request_invalid"; messages: string[] }
  | { kind: "request_failed"; message: string };
```

- [ ] 每次提交生成递增的本地 `requestId`。
- [ ] 新请求开始时中止上一个浏览器请求。
- [ ] 响应返回时，仅当它仍是最新 `requestId` 才更新页面。
- [ ] Agent 的 `failed` / `cancelled` 属于成功收到的 `RunResponse`，不要与断网混为一类。

建议 Hook：

```ts
function useResearchRun(
  createRun: (request: ResearchRequest, signal?: AbortSignal) => Promise<RunResponse>,
): {
  state: ResearchViewState;
  submit: (request: ResearchRequest) => Promise<void>;
  reset: () => void;
};
```

输入：可替换的请求函数，便于 mock 和真实 API 共用。

输出：当前视图状态、提交函数和重置函数。

功能：集中管理加载、成功、校验失败、网络失败、中止和旧响应保护。

### Step FE02.3：结果与错误组件

建议文件：

- `frontend/src/features/research/RunSummary.tsx`
- `frontend/src/features/research/ClaimList.tsx`
- `frontend/src/features/research/MissingInformation.tsx`
- `frontend/src/features/research/PublicErrorPanel.tsx`

- [ ] 展示 `run_id` 和外层状态。
- [ ] 分开展示 facts 与 inferences，避免把推断写成事实。
- [ ] 每条 claim 展示其 evidence IDs。
- [ ] 信息不足时突出 `missing_information`。
- [ ] 明确显示 `fixture` / `historical` / `live`，不得把 fixture 写成实时。
- [ ] 失败只显示 `PublicError.code`、`stage` 和 `message`。
- [ ] HTTP 422 只提取可公开的字段提示，不渲染任意 HTML。

建议函数：

```ts
function formatValidationMessages(payload: unknown): string[];
```

输入：HTTP 422 的未知 JSON 响应。

输出：可供表单显示的安全字符串列表。

功能：从 FastAPI `detail` 数组提取字段位置和提示；结构不合法时返回统一提示，不显示原始响应全文。

### Step FE02.4：mock 页面测试

- [ ] 表单四个字段能生成合法请求。
- [ ] `completed` 正确展示 facts、inferences、证据 ID 和 data mode。
- [ ] `insufficient_information` 正确展示缺失信息。
- [ ] `failed` / `cancelled` 不尝试读取 `result`。
- [ ] HTTP 422 显示字段错误。
- [ ] 较旧请求晚返回时不能覆盖较新请求。
- [ ] 页面不出现堆栈、API Key、原始异常或隐藏模型信息。

## 7. FE03：接入真实 API

目标：在 D09 完成后跑通 D10 的浏览器完整链路。

文件：`frontend/src/api/createRun.ts`

```ts
async function createRun(
  request: ResearchRequest,
  signal?: AbortSignal,
): Promise<RunResponse>;
```

输入：合法研究请求和可选的浏览器取消信号。

输出：后端公开的 `RunResponse`。

功能：发送 `POST /api/runs`，解析正常响应、HTTP 422 和不可用响应；不包含页面渲染逻辑。

- [ ] 通过开发代理或部署配置使用 `/api/runs`，不把地址散落在组件中。
- [ ] 请求头只声明 JSON，不在浏览器保存模型密钥。
- [ ] 区分 HTTP/网络失败、HTTP 422 和 Agent 安全终态。
- [ ] 验证响应中的 `run_id` 与当前页面结果绑定。
- [ ] 跑通 completed、insufficient information 和安全失败路径。
- [ ] 在浏览器确认旧响应保护有效。

完成标准：能现场说明一次请求从表单到 Agent、只读工具、结构化结果，再回到页面的完整路径。

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
│   │   ├── ResearchForm.tsx
│   │   ├── RunSummary.tsx
│   │   ├── ClaimList.tsx
│   │   ├── MissingInformation.tsx
│   │   ├── PublicErrorPanel.tsx
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

1. 先做 FE01，创建真实可运行的 React + TypeScript 工程和 mock 契约。
2. 继续做 FE02，独立完成页面状态和测试。
3. 后端 D09 稳定后做 FE03 联调，不要求 FE01/FE02 等待。
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

- [ ] FE01：定义 `RunResponse` 等同步响应类型。
- [ ] FE03：通过 `RunTransport` 隔离 mock 与真实 HTTP。
- [ ] FE06：只有后端事件协议稳定后，再增加 `SseRunTransport`、事件解析器和 reducer。
- [ ] 解析和状态归并使用纯函数测试，不依赖真实模型响应。

建议接口：

```ts
interface RunTransport {
  createRun(
    request: ResearchRequest,
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
