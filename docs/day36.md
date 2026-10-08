# Day36：LangGraph 按需研究工作流

## 完成结论

Day36 核心开发已完成。当前已经建立独立的 LangGraph 工作流，能够把一个研究问题拆成计划、按计划取数、检查证据充分性，并在最多一次补查后生成解释。

该工作流当前作为独立后端能力存在，尚未替换现有 `/api/research` 的 LangChain Agent 路径。Checkpoint、取消和恢复属于 Day37。

## 工作流

```text
START
  ↓
Planner
  ↓
Research
  ↓
Checker ── retry（最多一次）──→ Research
  │
  └─ enough / cannot_retry
              ↓
            Answer
              ↓
             END
```

节点职责保持分离：

- `Planner` 只生成声明式 `ResearchPlan`，不调用 Provider，也不生成市场观点；
- `Research` 复用已有 SEC、RAG、Financial、Market、Macro、Decision 和 Market Reaction 业务函数；
- `Checker` 只检查计划要求的结果是否存在、是否可用以及是否值得立即补查；
- `Answer` 没有工具，只能解释已经序列化的研究结果。

## State 与 Plan

`ResearchState` 保存：

| 字段 | 含义 |
| --- | --- |
| `request` | 原始 `ResearchRequest` |
| `plan` | Planner 生成的能力组合 |
| `results` | 各研究能力的原始结构化结果 |
| `missing_information` | Checker 确认的资料缺口 |
| `retry_count` | 已执行的补查次数 |
| `research_status` | `enough`、`retry` 或 `cannot_retry` |
| `output` | Answer 节点生成的最终文本 |

`ResearchPlan` 可以同时声明多个能力，不是单选路由。Macro Reaction 必须同时指定 `needs_macro=True` 和具体 `macro_release_type`；历史 Macro/Earnings Reaction 必须提供 1–20 的 history limit。字段组合不完整时由 Pydantic 直接拒绝。

低歧义问题优先使用确定性 Planner。例如“这次 CPI 后怎么走、之前 3 次表现如何，并结合技术面”会同时开启当前 Macro Reaction、3 次历史 Macro Reaction、Technical 和 Decision。需要理解财务 concept 或 SEC 文本问题时再使用结构化模型规划。

## 按需研究能力

| 用户需求 | Research 结果 |
| --- | --- |
| 公司资料 | 独立的 SEC submissions profile |
| 当前报价 | `quote` 与 `market_quality`，不加载日线 |
| 技术指标或观点 | 一次加载 Quote + 日线，复用 Technical、Quality 和 Decision |
| SEC 文本解释 | 按 Planner 给出的原问题调用 RAG，保留检索结果 |
| 结构化财务数字 | 按 concept、unit、period type 调用 Financial Service |
| 宏观数据 | `MacroSnapshot` 与质量结果 |
| 宏观市场反应 | 最近一次或指定数量的历史 Release + Reaction |
| 财报市场反应 | 最近一次或指定数量的历史 Earnings 8-K + Reaction |

未被 Plan 请求的能力不会访问对应 Provider。旧的 `get_company_profile` 教学工具继续保持 fixture 和离线契约；Day36 的真实公司资料使用单独的 `get_sec_company_profile`，避免让既有离线测试隐式访问网络。

## 补查与明确结束

Checker 默认把缺失信息视为终态。只有以下情况允许立即补查：

- Plan 要求的 capability 没有执行；
- Quote 明确记录 `quote_provider_unavailable`；
- Technical 明确记录 `bars_provider_unavailable`。

第一次出现可重试缺口时进入 `retry`。Research 再执行一次并把 `retry_count` 增加到 1；如果仍然缺失，Checker 写入 `cannot_retry` 并进入 Answer，不再循环。空的历史 Reaction 或空的 RAG 结果也会被识别为资料不足，不会伪装成完整证据。

Answer 在 `cannot_retry` 状态下仍可解释已有结果，但必须说明资料限制。它不能重新研究、修改 Decision、补写非 `usable` 的观察收益率或把事件前后关系描述成确定因果。

## 时间与兼容边界

- Earnings 历史查询最多扫描 100 份候选 8-K，再筛选 Item 2.02，并支持严格的 `before` 边界；
- Macro 历史发布日期按最近在前、严格 `before` 和 limit 选择；
- Longbridge 的供应商事件时间保存在 `vendor_release_at`，不能冒充已确认的 `released_at`；
- 普通研究可以使用合法的 vendor timestamp 做分钟对齐，但结果必须保留 `event_time_uses_vendor_timestamp` warning；
- 原有 `scheduled_release_at` 仍不能自动提升为实际发布时间；
- `EventTimeResolution.warnings` 已同步到新旧 Market Reaction 入口。

## 测试

Day36 专项覆盖：

- Plan 字段依赖校验；
- 当前事件、历史事件和技术研究的组合规划；
- “CPI 后 NVDA 怎么走”这类词序能够正确规划 Macro Reaction；
- 真实 `StateGraph` 的 `Planner → Research → Checker → Answer` 调用顺序；
- `ResearchContext` 通过 LangGraph Runtime 进入 Research 节点；
- Provider 首次失败后由真实 Checker、Router 和 conditional edge 补查，第二次恢复后进入 Answer；
- Provider 持续失败时最多补查一次并以 `cannot_retry` 结束；
- Quote-only 按需执行，不请求日线；
- Quote-only 从真实 Planner、Research、Quality、Checker、Answer 到 END 的完整工作流；
- `Technical + Decision` 联合意图只加载一次 Quote 和一次 Daily Bars，并产出 RSI14 与非 blocked Decision；
- Macro Reaction 正确等待线程结果，不向 State 写入 coroutine；
- Earnings latest/history 正确拆分；
- RAG 使用 Planner 给出的原始研究问题；
- dataclass、日期和 Decimal 的 Answer JSON 序列化；
- SEC 公司资料与旧 fixture Tool 隔离；
- 临时 Provider 失败只补查一次；
- 空历史证据明确结束。

运行专项测试：

```bash
backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  -c backend/pyproject.toml \
  backend/tests/test_langgraph_day36.py \
  backend/tests/test_langgraph_graph.py \
  backend/tests/test_langgraph_planner.py
```

运行本次相关回归：

```bash
backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  -c backend/pyproject.toml \
  backend/tests/test_langgraph_day36.py \
  backend/tests/test_langgraph_graph.py \
  backend/tests/test_langgraph_planner.py \
  backend/tests/test_earnings_reaction.py \
  backend/tests/test_market_reaction_alignment.py \
  backend/tests/test_macro_releases.py \
  backend/tests/test_macro_snapshot_builder.py \
  backend/tests/test_macro_temporal.py
```

运行完整后端：

```bash
backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  -c backend/pyproject.toml
```

真实 Workflow 测试使用编译后的 `StateGraph` 和真实业务节点，只替换外部 Provider 与 Answer Model，因此能够稳定验证 Graph 编排和业务调用边界，但它不等同于联网调用 Longbridge 或 SEC。

联网验收单独运行：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_day36_longbridge_workflow.py
```

该脚本只读调用真实 Longbridge，依次验证 Quote-only 只请求一次 Quote，以及 `Technical + Decision` 共用一次 Quote 和一次 Daily Bars；Answer 使用固定假响应，不调用真实模型。SEC + Longbridge 的最近财报联调继续由 `evals/verify_earnings_market_reaction.py` 覆盖。

最终 Live Smoke 使用真实 DeepSeek、LangGraph、Longbridge 和 Macro Provider：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  backend/examples/verify_langgraph_workflow.py
```

脚本覆盖当前报价、Technical + Decision、CPI Market Reaction 三个代表性问题。它要求 Planner 规划正确、对应 capability 确实执行、Checker 形成 `enough` 或 `cannot_retry` 终态并生成最终回答，但不会把真实数据暂时不可用误判成 Workflow 失败。

2026-10-08 验收结果：

- Day36 专项：`20 passed`；
- 本次相关回归：`68 passed`；
- 完整后端：`601 passed`；
- Day36 Longbridge 真实 Workflow：通过；
- Day36 DeepSeek + Longbridge + Macro Live Smoke：3 个场景通过；
- Pyright（Day36 LangGraph）：`0 errors`；
- Python 编译检查：通过；
- `git diff --check HEAD`：通过。

## 代码位置

- `backend/src/stock_agent/agents/langgraph/state.py`：Plan 与共享 State；
- `backend/src/stock_agent/agents/langgraph/planner.py`：确定性组合规划与模型 fallback；
- `backend/src/stock_agent/agents/langgraph/research.py`：按 Plan 编排现有业务能力；
- `backend/src/stock_agent/agents/langgraph/checker.py`：缺失信息、补查和终态判断；
- `backend/src/stock_agent/agents/langgraph/answer.py`：结果序列化与只读解释；
- `backend/src/stock_agent/agents/langgraph/graph.py`：图结构和初始 State；
- `backend/tests/test_langgraph_day36.py`：Day36 节点与业务契约验收；
- `backend/tests/test_langgraph_graph.py`：Graph 控制流、补查和真实节点工作流验收；
- `backend/tests/test_langgraph_planner.py`：联合意图规划验收；
- `evals/verify_day36_longbridge_workflow.py`：Day36 + Longbridge 真实只读联调。
- `backend/examples/verify_langgraph_workflow.py`：Day36 完整 Live Smoke。

## 下一步

Day37 加入 Checkpoint、取消和恢复演示，并验证恢复时哪些节点可以复用、哪些节点必须重跑，以及旧任务不能覆盖新任务。
