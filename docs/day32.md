# Day32：Trend、Momentum 与 Level 因子

## 目标

Day32 在 Day31 的 `MarketContext` 和 `FactorOpinion` 契约上实现三个确定性技术因子：

- `TrendFactor`：判断中期均线趋势是否同向；
- `MomentumFactor`：判断 5 日与 20 日价格动能，并用 RSI14 描述动能状态；
- `LevelFactor`：判断当前价格是否突破、跌破或接近关键价格区域；
- 每个结果保留固定规则版本、机器可读原因和实际参与判断的结构化证据；
- 不在 Day32 运行 Guard、合成最终 `DecisionResult`，也不输出涨跌概率或胜率。

## 数据流

```text
completed daily bars
        │
        ├─→ MA20 / MA50 / slope / MA200 ─→ TrendFactor
        ├─→ return_5d / return_20d / RSI14 ─→ MomentumFactor
        └─→ 20d high-low / Pivot levels / ATR distance ─→ LevelFactor
                                                        │
MarketContext.technical ────────────────────────────────┘
                                                        ▼
                                                  FactorOpinion
```

三个因子直接消费 `MarketTechnicalSnapshot`，不重复获取行情，也不重新计算已经由技术层提供的均线、收益率、ATR 或 Pivot 结构。

## 固定规则

### TrendFactor

必要输入为 `current_price`、MA20、MA50、MA20 五日斜率和 MA50 五日斜率：

| 条件 | signal | reasons |
| --- | --- | --- |
| `price > MA20 > MA50`，且两个 slope 均大于 0 | `bullish` | 均线多头排列、两条均线斜率为正 |
| `price < MA20 < MA50`，且两个 slope 均小于 0 | `bearish` | 均线空头排列、两条均线斜率为负 |
| 其他完整输入组合 | `mixed` | `trend_structure_not_aligned` |

MA200 只作为长期位置证据，存在时补充价格在 MA200 上方、下方或正好相等，不改变中期趋势方向。这样只有 50–199 根历史日线时，仍能形成中期趋势判断。

### MomentumFactor

5 日和 20 日收益率决定方向，RSI14 只描述当前动能状态：

| 5 日收益率 | 20 日收益率 | signal |
| --- | --- | --- |
| 正 | 正 | `bullish` |
| 负 | 负 | `bearish` |
| 0 | 0 | `neutral` |
| 其他组合 | `mixed` |

RSI14 使用 Wilder smoothing。需要至少 15 个完成收盘价；平均上涨和平均下跌都为 0 时返回 50，只有上涨时返回 100，只有下跌时返回 0。状态边界为：

- RSI > 70：`rsi_overbought`；
- 50 < RSI <= 70：`rsi_positive`；
- RSI = 50：`rsi_neutral`；
- 30 < RSI < 50：`rsi_weak`；
- RSI <= 30：`rsi_oversold`。

RSI 不反转收益率方向。例如两个收益周期均为正、RSI 为 75 时，结果仍为 `bullish`，同时记录 `rsi_overbought`。

### LevelFactor

LevelFactor 按以下优先级判断：

1. 当前价格高于最近 20 根完成日线最高价：`bullish`，记录向上突破；
2. 当前价格低于最近 20 根完成日线最低价：`bearish`，记录向下跌破；
3. 当前价格位于已聚合的 Pivot zone 内：`mixed`；
4. 最近支撑和阻力均不超过 0.5 ATR：`mixed`，表示处于狭窄结构区间；
5. 只有支撑或阻力不超过 0.5 ATR：`neutral`，只描述位置，不把支撑解释为必涨、阻力解释为必跌；
6. 有价格结构但不靠近关键位：`neutral`；
7. 没有任何可用价格结构：`insufficient_data`。

20 日突破优先于 Pivot zone 和 ATR 距离，确保同一时点只输出一个 Level 观点。

## 避免重复计分

Day32 不引入数值总分：

- MA 排列与 MA slope 共同形成一个 Trend 观点，不按多条相近信号重复加分；
- 5 日与 20 日收益率共同形成一个 Momentum 观点，RSI 仅作状态注释；
- 20 日高低点与 Pivot/ATR 共同形成一个 Level 观点，并按固定优先级只返回一次；
- 三个因子尚不合成为最终市场观点，综合流程留给 D33。

## 缺失数据与边界

- 没有 `technical` 时，三个因子均返回 `insufficient_data` 和 `technical_missing`；
- 任一 Trend 必要输入缺失时，不根据剩余均线强行判断方向；
- 任一 Momentum 必要输入缺失时，不使用 RSI 或单一收益周期替代完整判断；
- Level 缺少当前价格，或没有任何高低点、Pivot zone、支撑和阻力时，不输出方向；
- Data Quality Guard、过期行情阻断和最终 Decision 合成属于 D33，不在因子内部提前实现；
- 宏观数据和 Market Reaction 是独立研究上下文，不进入这三个技术因子的隐式评分。

## 代码位置

- `backend/src/stock_agent/decision/factors.py`：三个因子的规则和版本；
- `backend/src/stock_agent/market/indicators.py`：Wilder RSI14；
- `backend/src/stock_agent/market/technical.py`：把 RSI14 写入技术快照；
- `backend/tests/test_decision_day32.py`：Day32 专项规则测试；
- `backend/tests/test_market_technical.py`：技术快照集成断言。

## 测试

Day32 专项测试：

```bash
backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  backend/tests/test_decision_day32.py
```

专项测试覆盖：

- RSI Wilder smoothing、全平、连续上涨、连续下跌和历史不足；
- Trend 的 bullish、bearish、mixed、MA200 补充证据和必要输入缺失；
- Momentum 的 bullish、bearish、neutral、mixed、RSI 状态及必要输入缺失；
- Level 的 20 日突破/跌破、Pivot zone、0.5 ATR 边界、狭窄区间、中性位置及结构缺失；
- 三个因子在 Technical 缺失时都不输出 signal；
- 每个因子的固定规则版本和关键 evidence 字段。

## 完成情况

Day32 已于 2026-09-30 完成：

- Day32 专项测试：`20 passed`；
- D23、D31、D32 相关回归：`42 passed`；
- 完整后端回归：`525 passed`；
- `git diff --check`：通过。

D33 仍需实现 Data Quality Guard、Factors 执行顺序和最终 `DecisionResult` 合成；D34 再补完整 Decision Trace、反对理由和失效条件。
