# Day27：宏观发布事件与分钟行情时间对齐

Day27 建立 `MacroReleaseEvent` 与目标股票分钟行情的时间对齐流程。本日只解析事件时间、获取事件窗口行情、划分事件前后 K 线并判断数据是否足够；收益率计算留到 Day28。

## 调用流程

```text
MacroReleaseEvent + symbol + MarketDataProvider
       │ prepare_event_market_data()
       ▼
resolve_event_time()
       │ event_at
       ▼
fetch_event_intraday_bars()
       │ list[IntradayBar]
       ▼
align_event_with_bars()
       ├─ pre_bars
       ├─ crossing_bar
       └─ post_bars
       │
       ▼
assess_event_alignment()
       ├─ ready
       ├─ incomplete
       └─ unavailable
       │
       ▼
EventMarketAlignment
```

`prepare_event_market_data` 是 Day27 的正式编排入口，将发布事件、目标股票和对齐后的分钟行情保存在同一个 `EventMarketAlignment` 中。`resolve_event_time` 是事件时间的唯一解析边界；后续函数接收的 `event_at` 来自该解析结果，不在行情获取层重复依赖或验证 `MacroReleaseEvent`。

## 事件时间规则

- `released_at` 表示已确认的实际发布时间，是分钟级对齐的唯一时间依据；
- `scheduled_release_at` 只表示计划时间，不能替代 `released_at`；
- 缺少实际发布时间时返回 `actual_release_time_missing`，调用链停止，不获取分钟行情；
- 实际发布时间晚于 `as_of`、时间不带时区或与 `release_date` 冲突时拒绝对齐；
- 可用时间统一转换为 UTC，再传给行情查询和对齐函数。

## 分钟行情对齐

分钟 K 线使用半开区间 `[start_at, end_at)`：

- `bar.end_at <= event_at`：事件前 K 线；
- `bar.start_at >= event_at`：事件后 K 线；
- `bar.start_at < event_at < bar.end_at`：事件发生分钟的 `crossing_bar`。

因此，宏观数据在 `08:30:00` 整分钟发布时，`08:29–08:30` 属于事件前，`08:30–08:31` 属于事件后，不产生 crossing bar。

查询窗口按事件时间向前、向后展开并统一为 UTC。结束位置不会超过 `as_of`，从而避免读取研究截止时间之后的分钟行情。

## 对齐状态

`assess_event_alignment` 检查事件附近是否有足够的已完成行情：

- `ready`：事件前后都有距离不超过阈值的 K 线，具备进入后续计算的条件，但不表示事件附近数据完整；
- `incomplete`：事件前行情可用，但事件后的 K 线尚未完成或缺失；
- `unavailable`：事件前参考 K 线缺失或距离事件过远，无法进入后续计算。

事件时间不可用时，正式入口直接返回 `unavailable`，不会调用行情 Provider。分钟行情能力异常仍由 Provider 抛出，留到 Day28 转换成 Market Reaction 的结构化不可用结果。

分钟内部发生的事件若缺少 crossing bar，会记录非阻断 warning `event_minute_not_observed`。只要事件前后的完整 K 线可用，状态仍可以是 `ready`；这允许 Day28 继续计算较后的观察窗口，但不能据此计算发布后第一分钟的精确反应。

即使 crossing bar 存在，一分钟 OHLC 也不能精确还原宏观消息发布瞬间前后的逐笔价格。Day28 必须针对每个目标时点分别判断价格是否可用，不能把 `ready` 解释为所有收益率指标都可计算。

## 验收

专项自动化测试：

```bash
cd backend
.venv/bin/pytest -q -p no:cacheprovider \
  tests/test_market_reaction_alignment.py
```

测试覆盖：

- 计划发布时间不能冒充实际发布时间；
- 未来发布时间和日期冲突会被拒绝；
- 时区统一转换为 UTC；
- 查询窗口受 `as_of` 截止；
- 整分钟边界和分钟内部 crossing bar；
- `ready`、带非阻断 warning 的 `ready`，以及事件后 K 线未完成或已完成但缺失的 `incomplete` 状态；
- 正式入口在时间缺失时停止、在时间有效时关联事件与股票；
- 分钟行情能力异常继续留给 Day28 处理。

离线验收：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_day27_event_alignment_offline.py
```

离线脚本通过 `prepare_event_market_data` 使用 CPI fixture、NVDA 分钟 K 线和明确的实际发布时间跑通完整调用顺序，同时验证只有计划时间时会在调用 Provider 前停止。

## 已知限制

- 当前宏观 Provider 若不能确认实际发布时间，会保留 `released_at=None`，不会推测分钟级反应；
- Day27 不计算事件前参考价、T+5m、T+30m、T+1h 或收盘收益率，这些属于 Day28；
- Provider 能力异常转换为结构化不可用结果属于 Day28；
- 真实宏观事件端到端联调属于 Day30，本日验收为确定性的离线时间对齐。
