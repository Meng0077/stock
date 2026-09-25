# AI 辅助美股研究 Agent

这是一个面向 Agent 开发岗位的学习与演示项目。系统通过只读工具组合财报证据、结构化财务数据、行情与技术指标、宏观发布事件，并逐步加入宏观事件后的 Market Reaction，最终输出可追溯、可复算的研究结果。

项目按 [9 周、45 个开发日计划](stock-agent-python-development-plan.md) 推进。首版聚焦四条研究链路：

1. 财报 RAG 与结构化财务数据；
2. 行情与技术分析；
3. 宏观数据与 Surprise；
4. 宏观事件后的 Market Reaction。

新闻检索、用户仓位、个人风险建议、券商下单和自动交易不在首版范围内。本项目仅用于工程学习与研究演示，不构成投资建议。

## 当前进度

| 范围 | 状态 | 当前能力 |
| --- | --- | --- |
| D01–D10 Agent 基础 | 已完成核心链路 | Pydantic 契约、Manual Agent、LangChain Agent、只读工具、结构化输出和 FastAPI 薄接口 |
| D11–D18 财报与财务数据 | 已完成核心链路 | SEC 文档获取、按需索引、PostgreSQL/pgvector 持久化、增量更新、引用定位和 Company Facts |
| D19–D20 检索评估 | 延后 | 固定评估集和完整检索评估仍需收口 |
| D21–D22 行情 | 已完成 | 统一 Quote/Bar 契约、Fixture Provider、Longbridge 最新报价和至少 60 根已完成日线 |
| D23 技术分析 | 已完成 | MA5/20/50、收益率、ATR14、成交量、确认拐点及候选支撑阻力 |
| D24 宏观数据 | 进行中 | Provider、领域模型、纯计算、发布事件和 MacroSnapshot 已建立；继续完成全部真实数据联调 |
| D25–D45 | 待开发 | 时间有效性检查、Market Reaction、分析引擎、LangGraph、React 联调、评估与部署 |

各开发日的设计、验收记录和已知限制位于 [`docs/`](docs/)。当前状态以对应 day 文档和测试结果为准，不把 fixture、历史数据或尚未联调的能力描述为实时生产能力。

## 架构

```text
用户问题
   ↓
LangChain Agent ────────────────┐
   ├─ Knowledge Tool            │
   │    └─ SEC Documents → RAG  │
   ├─ Financial Tool            │
   │    └─ SEC Company Facts    │
   ├─ Market Tool               │
   │    └─ Quote / Bars → Technical Analysis
   └─ Macro Tool                │
        └─ MacroReleaseEvent → MacroSnapshot
                                 │
MacroReleaseEvent + 分钟行情 ──→ MarketReactionEngine（D26–D30）
                                 │
结构化结果 + Evidence + 时间边界 ┘
   ↓
Agent 解释结果，不改写工具数值或 Guard 结论
```

核心原则：

- RAG 负责非结构化资料与原文引用；
- 精确财务、行情和宏观数值来自结构化 Provider；
- 技术指标、Surprise 和 Market Reaction 使用确定性 Python 计算；
- 所有外部数据保留来源、事件时间、接收时间或统计期，并受任务 `as_of` 约束；
- Market Reaction 只描述事件前后的实际价格变化，不直接宣称因果关系。

## 技术栈

- 后端：Python 3.11、FastAPI、Pydantic、LangChain、SQLAlchemy
- 数据与检索：PostgreSQL、pgvector、Sentence Transformers
- 数据源：SEC EDGAR / Company Facts、Longbridge、BLS、BEA、FRED、Trading Economics、Federal Reserve、U.S. Treasury
- 前端：React 19、TypeScript、Vite、Tailwind CSS
- 测试：pytest、Vitest、React Testing Library

## 目录

```text
backend/
  src/stock_agent/
    agents/       Manual Agent、LangChain Agent 与输出校验
    api/          FastAPI 路由和公开响应
    documents/    SEC 文档发现、下载和解析
    financial/    SEC Company Facts 与精确财务指标
    macro/        宏观 Provider、模型、计算和 MacroSnapshot
    market/       行情 Provider、技术指标和价格结构
    retrieval/    分段、Embedding、索引和检索
    storage/      PostgreSQL / pgvector 持久化
    tools/        Agent 只读工具与注册表
  examples/       分阶段教学示例
  fixtures/       离线固定输入
  tests/          后端测试
docs/             每日实现、验收和遗留项记录
evals/            离线评估与真实 API 验证脚本
frontend/         React 前端；当前使用本地 Mock，尚未完成真实后端联调
```

Market Reaction 将在 D26–D30 开发，届时再创建对应目录，不预建空模块。

## 本地环境

### 1. 安装后端依赖

```bash
python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -r backend/requirements-dev.lock.txt
```

复制配置模板；`cp -n` 可避免覆盖已有密钥：

```bash
cp -n backend/.env.example backend/.env
```

按需要在 `backend/.env` 配置：

- 模型：`LLM_PROVIDER`、`DEEPSEEK_API_KEY` 或 `ZHIPU_API_KEY`、`MODEL_NAME`；
- 持久化：`STOCK_AGENT_DATABASE_URL`；
- 宏观：`FRED_API_KEY`，以及可选的 `TRADING_ECONOMICS_API_KEY`；
- Longbridge：`LONGBRIDGE_APP_KEY`、`LONGBRIDGE_APP_SECRET`、`LONGBRIDGE_ACCESS_TOKEN`。

不要提交 `backend/.env`，也不要把密钥写入代码、终端命令或聊天记录。

### 2. 启动后端

```bash
PYTHONPATH=backend/src backend/.venv/bin/uvicorn stock_agent.api.app:app --reload
```

当前开发接口：

| 方法与路径 | 说明 |
| --- | --- |
| `POST /api/runs` | 接收已归一化的 `ResearchRequest`，运行现有 Manual Agent 路径 |
| `POST /api/research` | 接收自然语言 `message`，识别 ticker 后运行 LangChain Agent |

目标公开接口为 `POST /api/chat/runs`，尚未完成。当前 API 是开发阶段契约，不代表 D36–D40 的最终工作流已经实现。

### 3. 启动前端

需要 Node.js 22.13+ 和 pnpm 11.22：

```bash
cd frontend
pnpm install
pnpm dev
```

前端当前使用本地 Fake Transport，不会调用真实后端或模型。更详细的命令、请求层和 SSE 边界见 [frontend/README.md](frontend/README.md)。

## 测试与验收

运行全部后端测试：

```bash
backend/.venv/bin/python -m pytest -c backend/pyproject.toml
```

运行前端检查：

```bash
cd frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

真实 API 验收与离线测试分开。常用在线验证入口：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python evals/verify_longbridge_market_data.py
PYTHONPATH=backend/src backend/.venv/bin/python evals/verify_day24_macro.py
```

这些脚本需要相应密钥和外部服务可用。宏观模块使用 FRED 获取官方发布日期；BLS ICS 因当前环境返回 403，已退出主链路。FRED 日期只有日期精度，不能单独用于 T+5m 等分钟级 Market Reaction。

## 文档入口

- [完整开发计划](stock-agent-python-development-plan.md)
- [D11：本地 RAG](docs/day11.md)
- [D13–D17：SEC Provider、按需索引与持久化](docs/day13.md)
- [D18：结构化财务数据](docs/day18.md)
- [D21–D22：行情 Provider](docs/day21_22.md)
- [D23：技术分析](docs/day23.md)
- [D24：宏观发布事件](docs/day24.md)
- [前端开发计划](docs/frontend-development-plan.md)
