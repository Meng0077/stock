# Day31：MarketContext 与 Decision 契约

## 目标

Day31 只定义多维市场分析引擎的输入输出契约，不实现趋势、动量和关键价位规则。完成标准是：

- `MarketContext` 聚合 Quote、`MarketTechnicalSnapshot`、`MacroSnapshot` 和可选 `MarketReactionResult`；
- 每个组件明确区分 `available`、`missing` 和 `not_requested`；
- 保留任务 `as_of`、组件数据来源、计算版本和质量规则版本；
- `FactorOpinion` 约束单个确定性因子的状态、方向、证据和规则版本；
- `DecisionResult` 约束最终状态、市场观点、因子列表、缺失信息和规则版本；
- 不在 Day31 计算 bullish/bearish 方向，实际 Factor、Guard 和综合规则分别留到 D32–D34。

## 预期流程

```text
Quote ───────────────┐
TechnicalContext ────┤
MacroSnapshot ───────┼─→ build_market_context()
MarketReaction ──────┤          │
DataQualityReport ───┘          ▼
                           MarketContext
                                │
                   component_statuses / provenance
                                │
                     D32 Factors → D33 Guards
                                │
                                ▼
                         DecisionResult
```

`build_market_context()` 只组装已经取得的数据并验证归属和时间边界，不负责请求 Provider、计算技术指标、构建宏观快照或计算 Market Reaction。

## 契约口径

### MarketContext

- `symbol` 统一去除首尾空格并转为大写；
- `as_of` 必须带时区；
- `requested_components` 记录本次研究真正需要的组件；
- 已请求但没有取得的数据标记为 `missing`，没有请求的数据标记为 `not_requested`；
- Quote、Technical 和 Market Reaction 必须属于 Context 的证券；
- 实际使用的数据时间不能晚于 `as_of`；未来 `target_at` 只允许处于尚未完成的观察状态；
- `market-context-v1`、技术计算版本、Market Reaction 计算版本、质量规则版本和真实数据来源必须进入 provenance。

### FactorOpinion

- `usable` 必须包含 `signal` 和至少一个机器可读 `reason`；
- `insufficient_data` 或 `blocked` 不得包含方向；
- `evidence` 保存规则实际使用的指标、值及结构化来源；
- `rule_version` 标识具体 Factor 规则版本。

### DecisionResult

- `complete` 和 `partial` 必须包含 `market_view`；
- `blocked` 不得包含 `market_view`；
- 同一种 Factor 不能重复出现；
- `rule_version` 与 Factor 自己的版本分别记录；
- opposing reasons、失效条件和完整 Decision Trace 在 D34 补充。

## 测试

Day31 专项测试：

```bash
backend/.venv/bin/pytest -q -p no:cacheprovider \
  backend/tests/test_decision_day31.py
```

新增的 8 个测试覆盖：

- MarketContext 默认固定版本，以及 missing/not-requested 状态；
- Context 版本不能被调用方任意覆盖；
- Quote 来源汇总和未来时间拒绝；
- MacroSnapshot 中每一条发布的时间检查；
- 实际发布时间来源与发布日期来源分开保留；
- Provider 失败时仍保留 Market Reaction 事件时间来源；
- 只有一期完整美债曲线时的来源汇总；
- FactorOpinion 与 DecisionResult 的状态不变量。

Day31 收紧了 `ObservationResult` 状态契约，Day29 的测试和离线验收输入已经同步补齐 `price` 与 `price_at`，Day29 专项测试仍为 `6 passed`，离线脚本通过。

## 完成情况

Day31 已于 2026-09-30 完成：

- `MarketContext` 可以通过 Builder 正常构建，版本固定为 `market-context-v1`；
- 组件状态可以区分 available、missing 和 not-requested；
- Quote、Technical、Macro、Market Reaction 和质量规则的来源及版本具备汇总入口；
- 宏观发布逐条执行时间检查，不会因缺少某条精确发布时间而跳过后续事件；
- `released_at_source` 与 `release_date_source` 分开保留，并传播到 Market Reaction 的 `event_time_source`；
- 单期和多期美债曲线均可保留对应数据来源；
- FactorOpinion 和 DecisionResult 的状态不变量已经建立。

验收结果：

- Day31 专项：`8 passed`；
- 完整后端回归：`504 passed`；
- Day29 离线兼容验收：通过；
- `git diff --check HEAD`：通过。

模型配置了 `frozen=True`，但部分字段使用可变容器；当前只禁止模型字段重新赋值，不承诺集合和列表的深层不可变。若后续需要跨线程共享不可变快照，再统一改为不可变容器，不在 Day31 提前扩展。
