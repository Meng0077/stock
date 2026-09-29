# Day29：市场基准比较与历史事件查询

Day29 在 Day28 单标的 Market Reaction 结果之上增加两项能力：同一宏观事件下的多标的研究与基准收益率比较，以及近期同类宏观发布的历史反应查询。

## 多标的研究

`research_multi_symbol_event_reaction()` 接收一次 `MacroReleaseEvent`、证券代码列表、行情 Provider 和 `as_of`，逐个复用 Day28 的 `research_event_reaction()`，返回 `MultiSymbolEventReaction`。

证券代码会去除首尾空格、转为大写并按首次出现顺序去重。空列表、单个字符串和空白代码会被拒绝。入口不维护固定 ETF 白名单，因此既支持 NVDA、QQQ，也支持当前 Provider 能查询的行业 ETF，例如 SOXX。

单个证券的行情能力缺失或 Provider 请求失败会由 Day28 服务边界转换成该证券自己的结构化不可用结果，不会覆盖已经取得的其他证券结果。

## 基准比较

`compare_event_symbols()` 从同一次多标的结果中选择目标证券和基准，分别比较 `5m`、`30m`、`1h` 和 `close`：

```text
difference_pp = 目标证券收益率（%）- 基准收益率（%）
```

结果单位是百分点，不是再次计算百分比变化。只有两侧观察结果都是 `usable` 且都有收益率时才返回 `difference_pp`。比较状态采用两侧较差的状态；优先级从低到高为 `usable`、`pending`、`missing`、`unavailable`。

比较前要求两侧属于同一个 `release_id`、`release_type` 和 `event_at`，对应观察窗口的 `target_at` 也必须相同。参考价格时间不同不会伪装成完全一致，而是在 `issues` 中记录 `reference_timestamp_mismatch`。

## 历史同类事件

`research_historical_multi_symbol_reactions()` 先通过 `select_historical_releases()` 按 `release_type`、`before`、`as_of` 和 `limit` 选择近期发布，再对每次发布执行相同的多标的研究。

历史结果按实际发布时间从近到远排列。`before` 与 `as_of` 都必须带时区，且不会选择边界时刻及其之后、在研究截止时间尚不可见，或缺少精确 `released_at` 的发布。

历史查询只返回能够进入分钟级反应计算的事件，因此日期精度事件不会占用 `limit` 名额。

## 验收

专项测试：

```bash
backend/.venv/bin/pytest -q -p no:cacheprovider \
  backend/tests/test_market_reaction_day29.py
```

覆盖内容：

- NVDA、QQQ、SOXX 的代码规范化、去重与多标的研究；
- 四个观察窗口的目标收益率减基准收益率；
- 基准观察窗口不可用时的状态降级；
- 空白证券代码拒绝；
- 单个标的 Provider 失败不影响其他标的；
- 近期同类宏观发布的类型、时间边界、精确发布时间、排序、数量限制和多标的反应查询。

离线验收：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_day29_comparison_offline.py
```

离线脚本验证 NVDA 相对 QQQ 的四个窗口百分点差、证券代码规范化，以及近期 CPI 发布的倒序选择。

## 已知限制

- 行业 ETF 是否可用取决于行情 Provider，不在本层维护固定证券列表；
- 比较结果描述共同事件窗口内的相对价格表现，不证明宏观事件与价格变化之间存在因果关系；
- 缺少精确实际发布时间的历史发布无法计算分钟级反应；
- 真实宏观事件、QQQ 和行业 ETF 行情的端到端联调已在 Day30 完成，结果见 [`day30.md`](day30.md)。
