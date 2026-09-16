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

业务步骤见 `../docs/frontend-development-plan.md`。
