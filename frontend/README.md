# Stock Agent Frontend

Stock Agent 的独立前端工程。FE01 已完成工程初始化、对话请求契约、结构化响应契约和固定 mock；尚未实现 FE02 研究对话页面。

## 技术栈

- React 19
- TypeScript 6
- Vite 8
- Tailwind CSS 4（官方 Vite 插件）
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

业务步骤见 `../docs/frontend-development-plan.md`。
