# Day25：数据新鲜度、时间有效性与缺失检查

Day25 在 Quote、日线技术分析和 MacroSnapshot 进入 Agent 前执行确定性质量检查。质量检查不修补数据，也不让模型自行决定是否忽略时间边界；每项结果统一标记为 `usable`、`degraded` 或 `rejected`。

## 统一质量结果

`DataQualityResult` 保存数据类型、目标、用途、状态、问题代码、研究截止时间和规则版本。`DataQualityReport` 汇总一次 Tool 调用中的 Quote、Bars 或宏观发布结果，并保留 Provider 局部失败产生的 `source_warnings`。

- `usable`：可以按原始语义使用；
- `degraded`：可以展示或用于不受影响的部分分析，但必须保留限制；
- `rejected`：不能进入对应事实或计算结果。

## Quote

Quote 检查缺失、ticker 不匹配、未来时间、fixture、过期、延迟状态和市场状态。

当前没有交易所日历，因此运行时允许 `market_state="unknown"`：

- 60 秒内的 Quote 返回 `degraded / market_state_unknown`，可以注明限制后展示；
- 超过 60 秒仍返回 `rejected / quote_stale`，unknown 不能绕过新鲜度检查；
- `rejected` Quote 不生成 evidence；
- `degraded` Quote 保留为独立 evidence，但不会混入历史技术指标的计算。

## 日线与技术分析

日线检查 ticker、周期、复权口径、旧到新排序、重复区间、未来数据、未完成 K 线和完成 K 线数量。默认要求 60 根完成日线，并单独列出 MA5/20/50、ATR14、5/20 日收益率、成交量和价格结构不可用的窗口。

`get_technical_analysis` 同时请求 Quote 和 60 根完成日线：

- Quote Provider 失败时，仍可返回通过检查的历史技术指标；
- Bars Provider 失败时，仍可返回 usable 或 degraded Quote；
- Bars 被拒绝时 `technical=None`；
- Quote 被拒绝时 `quote=None`；
- Quote 与技术指标使用不同 evidence ID 和 data mode。

## 宏观数据

完整 MacroSnapshot 和指定 `release_type` 都复用宏观时间校验：

- 排除发布时间晚于 `as_of` 的发布；
- 识别缺少可靠实际发布时间、统计期绑定未验证及 Actual 历史版本未验证；
- 识别供应商 Forecast 缺少发布前历史版本证明；
- 完整快照移除 rejected 发布，并在 `quality` 中保留拒绝原因；
- 普通在线研究可保留 degraded Estimated Surprise，但不能称为严格 PIT Surprise。

## 验收

离线测试：

```bash
cd backend
.venv/bin/pytest -q -p no:cacheprovider \
  tests/test_quality_quote.py \
  tests/test_quality_bars.py \
  tests/test_langchain_tools.py \
  tests/test_langchain_agent.py
```

真实长桥联调：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_day25_quality.py
```

在线脚本验证真实 Quote、至少 60 根完成日线、质量报告和 Technical evidence。休市时 Quote 可以因过期被拒绝，但日线技术分析仍应成功，不能把历史收盘价表述为实时价格。

2026-09-27 已完成真实长桥联调：NVDA Quote 在休市环境下被标记为 `rejected`，60 根完成日线为 `usable`，整体报告为 `degraded`，Technical evidence 正常生成，且没有 Provider 缺失警告。

## 已知限制

- 当前不判断交易所是否处于正常、盘前或盘后交易，默认使用 `unknown`；
- 休市 Quote 只作为 degraded 数据展示，不推断为经核实的最近收盘价；
- Longbridge 历史 Quote 和宏观 Actual 的严格历史 vintage 尚未验证；
- 分钟行情和宏观事件后的 Market Reaction 属于 D26–D30。
