# Day23：最小技术分析引擎

Day23 在统一的 `Quote` 和 `Bar` 之上计算确定性技术特征。行情提供方负责按 `as_of` 返回当时可见的数据，技术分析层不依赖 Longbridge 等供应商字段，也不从模型文本提取价格。

```text
MarketDataProvider
        ↓
Quote | None + Daily Bars
        ↓
prepare_technical_inputs()
        ↓
completed bars + current incomplete bar + quote
        ├── MA / Return / Wilder ATR
        ├── confirmed pivots / price levels
        └── current-bar structure
                        ↓
             MarketTechnicalSnapshot
```

## 输入规则

- MA、收益率、ATR 和历史价格结构只使用 `is_complete=True` 的日线。
- 实时查询可以单独使用最后一根 incomplete 日线生成 `CurrentBarStructure`，但不会把它混入历史指标。
- 当前参考价按 `Quote → incomplete bar close → latest completed close` 选择，同时保留价格来源和时间。
- 没有可用价格或历史窗口不足时，对应字段为 `None`，快照仍然可以生成。
- Pivot 只从调用方已经按 `as_of` 过滤过的完成日线中确认。

## 固定计算约定

| 特征 | 规则 |
| --- | --- |
| MA5 / MA20 / MA50 | 最近 N 个完成日收盘价的简单平均 |
| 5日 / 20日变化 | 最新完成日收盘价相对 N 个交易日前收盘价的百分比变化 |
| ATR14 | 前14个 TR 的简单平均作为初始值，后续使用 Wilder 平滑递推 |
| Recent high / low | 最近20根完成日线的最高价和最低价 |
| Pivot | 左右各两根完成日线确认 |
| Pivot 同价规则 | 左侧允许相等、右侧必须严格低于或高于，因此相同平台选择最右侧点 |
| Pivot 确认时间 | 右侧第二根完成日线的 `end_at` |
| 价位聚类 | Pivot 价格距离不超过 `0.25 × ATR14` 时归入同一价格区域 |
| 支撑/阻力 | 当前价下方/上方，按距离由近到远，各保留最多3个 |
| 价位距离 | 保存候选代表价与当前价的绝对距离及 ATR 倍数 |
| 成交量基准 | 最新完成日之前20个完成交易日的平均成交量 |
| RVOL | 最新完成日成交量除以前20日基准，使用倍数表示 |
| 成交量趋势 | 包含最新完成日的5日均量除以前20日基准 |

成交量使用提供方返回的数值，技术分析层不在本地做成交量复权，`volume_adjustment` 记录为 `provider_reported`。VWAP 需要可靠的分钟数据和交易时段定义，不在 Day23 当前实现范围内。

## 当前日线结构

`CurrentBarStructure` 只描述正在形成的日线，包括：

- 相对上一完成日收盘价的变化；
- 当前日内 high-low 振幅；
- 当前价在日内区间的位置；
- 距离日内高点的回撤；
- 相对日内低点的反弹。

如果最新 Quote 超出当前 Bar 已记录的 high-low，计算时会使用 Quote 扩展有效区间，但保留 Bar 自身的 close。

## 验收

```bash
cd backend
source .venv/bin/activate
pytest -q tests/test_market_technical.py tests/test_market_volume.py
```

固定 OHLCV 测试覆盖：

- 完整历史上的 Wilder ATR 递推；
- MA5 / MA20 / MA50 和固定窗口收益率；
- 前20日成交量基准、RVOL、5日成交量趋势和历史不足；
- 零成交量基准以及 incomplete Bar 隔离；
- Pivot 同价选择和确认时间；
- 支撑/阻力距离、排序和数量上限；
- 数据不足时生成空结构；
- Day21 fixture 到技术快照的完整组装；
- 仅有完成日线、完全没有行情以及实时 incomplete bar 三种输入；
- 下跌 Swing 的 Fibonacci 方向。

模型只负责解释这些结构化结果，不负责修改指标数值、补齐缺失值或把候选价位描述成必然有效的支撑和阻力。
