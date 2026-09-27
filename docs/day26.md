# Day26：历史分钟行情契约与长桥接入

Day26 为后续 Market Reaction 提供历史分钟行情，不在本日计算事件收益率。当前支持 1 分钟粒度，统一保留 OHLCV、时间区间、时区、数据源、复权口径、数据模式和交易时段。

## 数据契约

`IntradayBar` 继承通用 `Bar`，并将 `timeframe` 固定为 `1m`。`session` 明确区分：

- `pre`：盘前；
- `regular`：正常交易时段；
- `post`：盘后；
- `overnight`：隔夜；
- `unknown`：供应商未提供可识别的时段。

`HistoricalMinuteBarsRequest` 使用 `[start_at, end_at)` 时间区间，并要求 `start_at`、`end_at` 和 `as_of` 都带时区。查询窗口不能结束在 `as_of` 之后。

`get_intraday_bars` 与已有的 `get_bars` 保持一致，直接返回 `list[IntradayBar]`：

- 返回 `[]` 只表示 Provider 支持分钟历史查询，但指定区间内没有数据；
- Provider 没有配置或不支持分钟历史查询时抛出 `MarketDataCapabilityError`；
- Provider 请求失败仍抛出 `MarketDataProviderError`，不伪装成正常空数据。

Fixture Provider 通过是否配置 `(symbol, "1m")` 区分能力缺失和空数据。长桥 Provider 使用 `Period.Min_1`、`AdjustType.NoAdjust` 和 `TradeSessions.All`，按时间向历史方向分页，并对分页边界重复数据去重。

## 时间与交易时段

长桥 Python SDK 返回主机本地时间语义的 naive `datetime`。Mapper 先按主机本地时区解释，再统一转换为 `America/New_York`，避免把北京时间直接当作美东时间。

长桥每根 Candlestick 的 `trade_session` 映射为系统内部的盘前、正常盘、盘后或隔夜时段。`IntradayCoverage` 统计每个要求时段实际观察到的 K 线数量；未观察到只表示本次数据没有覆盖，不能推断供应商永久不支持该时段。

## 质量检查

`validate_intraday_bars` 检查：

- symbol、1 分钟长度及整分钟对齐；
- 已完成状态和 `as_of` 时间边界；
- 时间排序、重复和重叠；
- 复权口径及数据模式是否一致；
- 必需交易时段是否观察到；
- 更新时间和未知交易时段。

能力缺失由 Provider 通过 `MarketDataCapabilityError` 明确表达，不在质量函数内提前分类。必需时段全部未观察到时拒绝计算，部分未观察到时降级。

## 验收

专项自动化测试：

```bash
cd backend
.venv/bin/pytest -q -p no:cacheprovider \
  tests/test_intraday_market.py
```

专项测试覆盖请求时区与时间边界、Fixture 空数据和能力异常、分钟质量检查、交易时段覆盖、长桥 session 映射、分页去重及分页冲突。

离线验收：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_day26_intraday_offline.py
```

离线脚本验证盘前、正常盘和盘后样例均可通过质量检查，同时验证未配置分钟数据时会抛出明确的能力异常。

真实长桥联调：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_day26_intraday.py
```

2026-09-27 已使用 NVDA 2026-09-25 的真实历史行情完成联调：

- 共返回 960 根已完成 1m K 线；
- 时间范围为 `2026-09-25 04:00–20:00 America/New_York`；
- 盘前 330 根、正常盘 390 根、盘后 240 根；
- 隔夜时段未观察到，因此全时段覆盖状态为 `partially_observed`；
- 正常交易时段质量结果为 `usable`。

## 已知限制

- 当前只支持 1 分钟粒度；
- 单次查询最多向历史翻 12 页，每页最多 1000 根；
- 当前验收只证明 NVDA 指定交易日的盘前、正常盘和盘后数据可取得，未证明隔夜行情覆盖；
- 宏观事件时间对齐属于 D27，T+5m、T+30m、T+1h 和收盘收益计算属于 D28；
- `MarketDataCapabilityError` 当前只在 Provider 边界明确抛出；将其转换为 Market Reaction 的结构化不可用结果遗留到 D28；
- Longbridge SDK 的 naive 时间依赖运行机器本地时区配置，部署环境必须保持系统时区正确。
