# Earnings Market Reaction：财报披露后的市场反应

## 目标

该扩展在不重写 D26–D30 Market Reaction 计算引擎的前提下，支持以下问题：

- “NVDA 最近一次财报后怎么走？”
- “财报披露后 5 分钟、30 分钟和 1 小时表现如何？”
- “财报披露后的正式收盘反应如何？”

数据流程为：

```text
SEC submissions
    │
    └─→ 最近 20 份 8-K
             │
             └─→ Primary filing 包含 Item 2.02
                      │
                      └─→ EarningsReleaseEvent
                               │
                               └─→ research_timed_event_reaction
                                        ├─ 5m / 30m / 1h
                                        └─ official close
```

## 财报事件契约

`EarningsReleaseEvent` 保留：

| 字段 | 含义 |
| --- | --- |
| `event_id` | `earnings:<symbol>:<accession_number>` |
| `symbol` | 标准化后的证券代码 |
| `released_at` | SEC filing `accepted_at` |
| `released_at_source` | 固定为 `sec_8k_accepted_at` |
| `report_date` | SEC filing 报告日期，可为空 |
| `accession_number` | SEC accession number |
| `source_url` | 8-K primary document URL |
| `warnings` | 固定保留 `event_time_uses_sec_8k_acceptance` |

第一版只识别 SEC 8-K Item 2.02，即 `Results of Operations and Financial Condition`。会先读取 primary filing，不会把任意 8-K 都当作财报。

SEC Provider 同时把 8-K 纳入支持表单，并允许选择 HTML 格式的 EX-99 附件，便于后续检索财报新闻稿；当前事件身份判断仍以 primary 8-K 的 Item 2.02 为准。

## 通用 Timed Event Reaction

Market Reaction 的行情对齐和计算已收口到通用入口：

```python
research_timed_event_reaction(
    event_id=...,
    event_type=...,
    event_at=...,
    event_time_source=...,
    symbol=...,
    provider=...,
    as_of=...,
    extra_issues=...,
)
```

该入口不解析事件身份，只负责：

- 获取事件前后分钟行情；
- 选择 reference price；
- 计算 5m、30m、1h 和正式收盘窗口；
- 把分钟/日线能力异常保留为结构化结果；
- 传播事件时间来源和限制说明。

原有 `research_event_reaction()` 仍是宏观发布入口：它先使用 `resolve_event_time()` 解析 `MacroReleaseEvent`，再委托通用入口。现有 CPI/PPI/PCE 等路径保持兼容。

`MarketReactionResult` 为了兼容原有契约，仍使用 `release_id` 和 `release_type` 字段；对财报事件，它们分别保存 earnings event ID 和 `earnings`。

## Agent Tool

`get_earnings_market_reaction` 只向模型暴露 `company_id`。`as_of` 和 Market Provider 仍由 `ResearchContext` 注入，模型不能传入或猜测 `event_at`、`event_id` 和参考价。

成功返回：

- 结构化 `earnings` 事件；
- 完整 `MarketReactionResult`；
- `data_mode="historical"`；
- Evidence ID：`market-reaction:<earnings_event_id>:<symbol>`；
- `event_time_uses_sec_8k_acceptance` warning。

当 `as_of` 之前没有可确认的 Earnings 8-K 时，Tool 返回 `earnings=null` 和 `reaction=null`，且不生成 Evidence。

Agent Prompt 区分：

- 财务数值使用 `get_financial_facts`；
- 管理层解释、MD&A 和风险使用 `retrieve_knowledge`；
- 财报披露后实际股价变化使用 `get_earnings_market_reaction`。

这三类结果保持独立，不因财务数据好就推导股价应该上涨，也不因股价下跌就改写财报事实。

## 时间与因果边界

SEC `accepted_at` 表示 filing 被 SEC 接收并公开的时间，不保证它是公司新闻稿最早对外发布时间。因此回答必须明确说明观察窗口以 SEC 8-K acceptance timestamp 为基准。

Market Reaction 只证明事件时间前后实际观察到的价格变化，不证明财报内容与价格变化存在确定因果关系。`pending`、`missing` 和 `unavailable` 状态不得被模型补写成具体收益率。

## 已知限制

- 仅检查最近 20 份 8-K；
- 仅用 primary filing 中的 Item 2.02 文本确认事件；
- 暂不对 8-K/A、6-K 外国发行人财报或公司新闻稿最早时间做扩展；
- SEC 文档获取失败仍按原 SEC 边界向上传播，本次不新增重试、缓存或通用异常吞掉；
- 这是事件研究工具，不是财报利好/利空评分系统。

## 代码位置

- `backend/src/stock_agent/market/earnings.py`：8-K 识别、财报事件和 Reaction 入口；
- `backend/src/stock_agent/market_reaction/alignment.py`：通用 timed event 行情对齐；
- `backend/src/stock_agent/market_reaction/service.py`：通用 Reaction Service 和宏观兼容入口；
- `backend/src/stock_agent/agents/langchain/langchain_tools.py`：Agent Tool；
- `backend/src/stock_agent/agents/langchain/langchain_agent.py`：Tool 路由和非因果约束；
- `backend/src/stock_agent/agents/evidence.py`：Evidence 白名单；
- `backend/tests/test_earnings_reaction.py`：事件识别、委托和结构化失败测试。

## 验收

相关回归：

```bash
backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  backend/tests/test_earnings_reaction.py \
  backend/tests/test_langchain_tools.py \
  backend/tests/test_langchain_agent.py \
  backend/tests/test_evidence_validation.py \
  backend/tests/test_sec_provider.py \
  backend/tests/test_market_reaction.py \
  backend/tests/test_market_reaction_alignment.py \
  backend/tests/test_market_reaction_day29.py \
  backend/tests/test_market_reaction_day30.py
```

- 相关回归：`159 passed`；
- 完整后端：`572 passed`；
- 本次生产文件 Pyright：`0 errors`；
- `git diff --check HEAD`：通过。

### SEC + Longbridge 真实联调

真实外部服务验收与默认离线 pytest 分开，避免网络、密钥或供应商状态影响日常回归。运行：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_earnings_market_reaction.py
```

该脚本动态使用运行时刻作为 `as_of`，通过 SEC 找到 NVDA 最近一次 Item 2.02 8-K，再通过 Longbridge 计算 5m、30m、1h 和正式收盘反应。验收要求包括：

- SEC 事件 ID、accession number、`accepted_at` 和来源 URL 一致；
- reference price 来自 Longbridge 且位于事件时间之前；
- 四个观察窗口均为 `usable`，价格、时间与收益率完整；
- 所有行情证据来源均为 Longbridge，且不超过本次 `as_of`。

2026-10-07 使用真实 SEC 与 Longbridge 数据完成一次 NVDA 联调：

| 项目 | 实际结果 |
| --- | --- |
| SEC accession number | `0001045810-26-000073` |
| SEC accepted_at | `2026-08-26 20:21:19+00:00` |
| reference | `206.500`，`2026-08-26 16:21:00-04:00` |
| 5m | `207.883`，`+0.6697%`，`usable` |
| 30m | `209.660`，`+1.5303%`，`usable` |
| 1h | `218.100`，`+5.6174%`，`usable` |
| next official close | `227.980`，`+10.4019%`，`usable` |

本次结果只表示相对 SEC `accepted_at` 的实际价格变化，不证明财报内容与价格变化之间存在确定因果关系。
