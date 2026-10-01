# Day33：Guard、Factors 与 Decision 纯函数流程

## 目标

Day33 把 Day31 的 `MarketContext`/`DecisionResult` 契约与 Day32 的三个技术因子串成确定性决策流程：

```text
MarketContext
     │
     ▼
Technical Guard
     │
     ├─ blocked ───────────────────────────────→ DecisionResult
     │
     ▼
Trend → Momentum → Level
     │
     ▼
complete / partial / blocked
     │
     ▼
deterministic market_view ─────────────────────→ DecisionResult
```

该流程不获取行情、不重新计算技术指标、不让模型参与方向判断，也不把宏观或 Market Reaction 隐式转换成技术评分。

## Guard 规则

Technical 是当前技术决策唯一必需的组件。Quote 不是硬依赖，因为 `MarketTechnicalSnapshot.current_price` 可以来自未完成日线或最近完成日线收盘价。

| 条件 | 处理 |
| --- | --- |
| `context.technical` 缺失 | `blocked`，记录 `technical_missing`，不运行 Factors |
| Technical 质量为 `rejected` | `blocked`，记录 `technical_quality_rejected`，不运行 Factors |
| Technical 质量为 `degraded` | 继续运行，追加 `technical_quality_degraded` warning |
| Technical 质量为 `not_assessed` | 继续运行，但追加 `technical_quality_not_assessed`，不能静默宣称质量可用 |
| Technical 质量为 `usable` | 正常运行 Factors |

数据时间边界由 `MarketContext` 契约在进入 Decision Engine 前检查：Technical 的 `price_at`、Quote 时间、宏观 `as_of` 以及 Market Reaction 实际观察时间均不得晚于任务 `as_of`。Decision Engine 消费已经通过该契约的数据，不重复实现时间校验。

## Factor 执行和 Decision 状态

三个因子固定按 Trend、Momentum、Level 顺序执行，结果全部保留在 `DecisionResult.factors` 中。

| 可用因子数量 | Decision status | market_view |
| --- | --- | --- |
| 3 | `complete` | 按固定合成规则生成 |
| 1–2 | `partial` | 根据可用因子生成，同时记录缺失原因 |
| 0 | `blocked` | `None`；保留三个不可用 Factor 及缺失原因 |

`missing_information` 来自不可用 Factor 的机器可读 reasons。硬 Guard 在 Factors 运行前阻断时，Factors 为空；Factors 已运行但全部不可用时，Factor 结果仍保留，避免丢失指标完整性信息。

## 市场观点合成

Trend 是整体方向的主要锚点，Momentum 用于确认趋势或识别明确冲突。两者都可用时按下表合成基础 market view：

| Trend | Momentum | Market view | 含义 |
| --- | --- | --- | --- |
| `bullish` | `bullish` | `bullish` | 趋势与动能一致 |
| `bullish` | `mixed` | `bullish` | 趋势向上，但动能分化 |
| `bullish` | `neutral` | `bullish` | 趋势向上，动能暂时平 |
| `bullish` | `bearish` | `mixed` | 趋势与动能明确冲突 |
| `bearish` | `bearish` | `bearish` | 趋势与动能一致 |
| `bearish` | `mixed` | `bearish` | 趋势向下，但动能分化 |
| `bearish` | `neutral` | `bearish` | 趋势向下，动能暂时平 |
| `bearish` | `bullish` | `mixed` | 趋势与动能明确冲突 |
| `mixed` | `bullish` | `mixed` | 动能转强，但趋势尚未确认 |
| `mixed` | `bearish` | `mixed` | 动能转弱，但趋势尚未确认 |
| `mixed` | `mixed` / `neutral` | `mixed` | 都没有形成明确趋势 |

因此，Momentum 的 `mixed` 或 `neutral` 表示动能没有完成方向确认，不会自动推翻已经形成的 bullish/bearish Trend；只有 Momentum 与明确 Trend 方向相反时，基础观点才变为 `mixed`。Trend 本身为 `mixed` 时，即使 Momentum 已经转强或转弱，也不足以单独把整体观点升级为明确方向。

其他合成规则保持不变：

1. 只有一个主要因子可用时，使用该因子的 signal 作为 partial Decision 的基础方向；
2. Trend 与 Momentum 都不可用时，才使用 Level 的 signal；
3. Level 的 `bullish` 突破与 bearish 基础方向冲突，或 `bearish` 跌破与 bullish 基础方向冲突时，最终改为 `mixed`；
4. Level 的 `neutral` 和 `mixed` 只描述位置，不覆盖基础方向。

规则版本固定为 `decision-v1`。它是可复算规则标识，不是涨跌概率、置信概率或历史胜率。

## 独立研究上下文

Macro 和 Market Reaction 不参与 Day33 的技术方向合成：

- 未请求或缺失 Macro，不自动填充宏观判断；
- 未请求或缺失 Market Reaction，不推测事件后价格表现；
- 即使 Context 声明请求了它们但数据缺失，技术 Decision 仍只反映 Technical；
- 宏观实际值、Estimated Surprise 和已观察 Market Reaction 的独立解释留给后续 Agent 层。

这保证“技术面观点”不会被伪装成“宏观因果结论”。

## 审查修正

检查初始实现时发现并修正两处结果丢失问题：

- blocked 辅助函数原先忽略传入的 `missing_information`，所有阻断都错误返回 `technical_missing`；现已保留真实 Guard 原因；
- Factors 已执行但全部不可用时，原先清空 `factors`；现保留三个 `FactorOpinion`，使指标缺失原因可复核。

原有规则说明注释均予以保留。

## 代码位置

- `backend/src/stock_agent/decision/engine.py`：Guard、Factor 执行、Decision 状态和方向合成；
- `backend/src/stock_agent/decision/factors.py`：Day32 的三个确定性因子；
- `backend/src/stock_agent/decision/models.py`：MarketContext、FactorOpinion 与 DecisionResult 契约；
- `backend/tests/test_decision_day33.py`：Day33 专项测试。

## 测试

专项测试：

```bash
backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  backend/tests/test_decision_day33.py
```

12 个专项用例覆盖：

- Technical 缺失和质量 rejected 的硬阻断；
- usable、degraded、not-assessed 三种可继续状态；
- aligned bullish/bearish 完整结果；
- Trend/Momentum 分歧与 Level 反向突破冲突；
- 主因子缺失、只有 Level 可用以及全部因子不可用；
- blocked 原因和不可用 Factor 不丢失；
- Macro/Market Reaction 缺失不污染技术 Decision。

## 完成情况

Day33 已于 2026-10-01 完成：

- Day33 专项测试：`12 passed`；
- D31–D33 跨日回归：`40 passed`；
- 完整后端回归：`537 passed`；
- `git diff --check HEAD`：通过。

D34 已在现有 Factor evidence 和 Decision 结果之上补充 Decision Trace、反对理由和失效条件，见 [`day34.md`](day34.md)。
