# Stock Agent Frontend

Stock Agent 的独立前端工程。当前只完成工程初始化，不包含研究业务页面。

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

业务步骤见 `../docs/frontend-development-plan.md`。
