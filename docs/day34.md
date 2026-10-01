# Day34：Decision Trace、反对理由与失效条件

## 目标

Day34 在 Day33 的确定性 Decision 流程上补齐公开、可复算的 Decision Trace。这里的 Trace 是业务规则轨迹，不是模型隐藏思维过程：

```text
MarketContext
    │
    ├─ Factor evidence
    │    ├─ 指标实际值
    │    ├─ 固定阈值
    │    └─ Technical 字段或规则来源
    │
    ├─ Factor signal / reasons / rule_version
    │
    ├─ decision_reasons
    ├─ opposing_reasons
    ├─ invalidation_conditions
    └─ Decision rule_version
```

这些字段共同解释“使用了什么输入、经过哪条固定规则、为什么形成当前观点、哪些信息与观点相反，以及什么变化要求重新评估”。

## Trace 契约

Day34 沿用 `DecisionResult`，不额外复制一套平行 Trace 对象：

| 字段 | 作用 |
| --- | --- |
| `factors[].evidence` | 实际指标值、固定阈值及结构化来源 |
| `factors[].signal` | 单个 Trend、Momentum 或 Level 结论 |
| `factors[].reasons` | Factor 内部命中的机器可读规则 |
| `factors[].rule_version` | 单个 Factor 的规则版本 |
| `decision_reasons` | Decision 层如何合成最终 `market_view` |
| `opposing_reasons` | 明确方向中仍存在的反面或未确认信息 |
| `invalidation_conditions` | 会使当前判断依据失效、要求重新计算的可观察变化 |
| `rule_version` | Decision 合成规则版本 |

契约要求 `complete` 和 `partial` Decision 必须包含 `decision_reasons`。`blocked` 没有方向，因此不得携带 `decision_reasons`、`opposing_reasons` 或 `invalidation_conditions`；如果 Factors 已经运行，其不可用结果仍保留在 `factors` 和 `missing_information` 中。

## 指标、阈值与价格来源

Factor evidence 在 Day32 指标值基础上补充以下规则输入：

### Trend

- `current_price` 及 `technical.current_price` 字段来源；
- `current_price_source`，例如 `quote`、`incomplete_bar` 或 `completed_close`；
- MA20、MA50、两条五日 slope 及可选 MA200；
- `slope_direction_threshold_pct=0`，来源为 `rule.trend-v1`。

价格与 MA20、MA50 的动态比较阈值就是 evidence 中对应的实际均线值；斜率使用显式零阈值。

### Momentum

- 5 日和 20 日收益率、RSI14；
- `return_direction_threshold_pct=0`；
- RSI 的 70、50、30 三个固定边界；
- 固定阈值来源为 `rule.momentum-v1`。

### Level

- 当前价格及 `current_price_source`；
- 最近 20 日高低点，作为突破/跌破的动态阈值；
- 最近支撑、阻力及各自 ATR 距离；
- 当进入 ATR 邻近判断时，记录 `near_level_atr_threshold=0.5`，来源为 `rule.level-v1`。

只记录实际进入规则路径的阈值。例如已经命中 20 日突破时，不会再伪装成使用了后续 0.5 ATR 邻近判断。

## Decision 组合理由

`decision_reasons` 记录 Decision 层的规则路径，常见值包括：

| reason | 含义 |
| --- | --- |
| `primary_factors_aligned` | Trend 与 Momentum 明确同向 |
| `trend_direction_retained_without_momentum_confirmation` | Trend 明确，Momentum 为 mixed/neutral，保持 Trend 方向但缺少动能确认 |
| `trend_momentum_conflict` | Trend 与 Momentum 明确反向，结果为 mixed |
| `trend_not_directional` | Trend 本身为 mixed，Momentum 不足以单独升级整体方向 |
| `trend_only_available` | partial Decision 只能使用 Trend |
| `momentum_only_available` | partial Decision 只能使用 Momentum |
| `level_only_available` | 两个主要因子都不可用，只能使用 Level |
| `level_confirms_primary_direction` | Level 的明确突破方向与主要方向一致 |
| `level_conflicts_with_primary_direction` | Level 的明确突破方向与主要方向相反，结果变为 mixed |
| `level_no_directional_override` | Level 为 neutral/mixed，不覆盖主要方向 |
| `level_does_not_resolve_primary_conflict` | 主要因子已经冲突，Level 不通过投票消除冲突 |

## 反对理由

`opposing_reasons` 只服务明确的 `bullish` 或 `bearish` 观点。`mixed`/`neutral` 本身已经表示没有单一方向，其原因由 Factors 和 `decision_reasons` 表达，不重复生成反对理由。

- bullish 中，Momentum mixed/neutral 会记录 `momentum_not_confirmed` 及具体动能原因；靠近阻力、处于关键 zone 或狭窄区间也会保留；
- bearish 中，下方支撑、关键 zone 或狭窄区间属于反面结构因素；
- 反对理由不会反过来覆盖确定性 `market_view`，只用于完整展示证据的两面。

## 失效条件

明确方向的失效条件直接对应原规则：

- bullish Trend：价格不再高于 MA20、MA20 不再高于 MA50、任一 slope 不再为正；
- bearish Trend：价格不再低于 MA20、MA20 不再低于 MA50、任一 slope 不再为负；
- Momentum 明确转向当前观点的反方向；
- 价格发生与当前观点相反的 20 日突破或跌破。

mixed 观点也有可复算的重新评估条件：

- Trend/Momentum 冲突：任一方不再反对另一方；
- Trend 尚未形成方向：Trend 转为 bullish 或 bearish；
- Level 与主要方向冲突：Level 不再冲突或主要方向发生改变。

初始实现曾在 `market_view=mixed` 时提前返回空列表，使上述 mixed 条件不可达；Day34 验收已修正并增加回归测试。

## 宏观与 Market Reaction 边界

Decision Trace 只解释技术 Decision，不把独立研究上下文变成隐式技术评分：

- 宏观 Actual 保留在 `MacroReleaseEvent.metrics[].actual`；
- Consensus 与 Estimated Surprise 保留在宏观结构中，且非 PIT 限制继续保留；
- 已观察 Market Reaction 保留事件时间、参考价、观察窗口及基准相对收益；
- 它们不写入 Trend/Momentum/Level 的 `decision_reasons`，也不被描述为已证明的因果关系。

D35 Agent 整合时应分别展示这些结构化结果，不能用模型文字覆盖数值、时间边界、Guard 或技术 Decision。

## 代码位置

- `backend/src/stock_agent/decision/factors.py`：指标、固定阈值和价格来源 evidence；
- `backend/src/stock_agent/decision/engine.py`：组合理由、反对理由和失效条件；
- `backend/src/stock_agent/decision/models.py`：Decision Trace 状态不变量；
- `backend/tests/test_decision_day34.py`：Day34 专项测试。

## 测试

专项测试：

```bash
backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  backend/tests/test_decision_day34.py
```

8 个专项用例覆盖：

- 指标值、零阈值、RSI 阈值、0.5 ATR 阈值和当前价格来源；
- bullish 中 Momentum 未确认与靠近阻力；
- bearish 中靠近支撑；
- Trend/Momentum 冲突、Trend mixed 和 Level 冲突的重新评估条件；
- Level 突破方向与主要方向一致时的确认路径；
- 非阻断 Decision 必须包含组合理由，blocked 不得包含方向性 Trace。

## 完成情况

Day34 已于 2026-10-01 完成：

- Day34 专项测试：`8 passed`；
- D31–D34 跨日回归：`48 passed`；
- 完整后端回归：`545 passed`；
- `git diff --check HEAD`：通过。

D35 仍需把 MarketContext、DecisionResult、MacroSnapshot 和 MarketReaction 作为独立结构化结果交给 Agent，并验证 Agent 不改写其数值和结论。
