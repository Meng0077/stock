# Day30：Market Reaction 离线验收与真实联调

## 完成状态

Day30 核心验收已于 2026-09-29 完成：离线测试覆盖计划要求的异常和时间边界；真实联调使用一项 BLS 宏观发布以及 Longbridge 的 NVDA、QQQ、SOXL 历史行情，完成分钟反应、正式收盘反应和基准差异计算。

本日没有接入模型，也没有交易写操作。真实验收脚本只读取宏观发布时间和历史行情。

## 离线验收

专项命令：

```bash
backend/.venv/bin/pytest -q -p no:cacheprovider \
  backend/tests/test_market_reaction_day30.py
```

2026-09-29 的结果为 `12 passed`。完整后端回归结果为 `496 passed`。

| 计划要求 | 对应验证 |
| --- | --- |
| 盘前发布 | 标准事件发生在 08:30 ET，并验证事件前参考价及 5m、30m、1h、close 四个窗口 |
| 交易时段切换 | 09:15 ET 事件的 30m、1h 跨越 09:30 开盘，仍按墙上时间计算 |
| 休市 | 2026-01-01 的目标正式收盘被解析到下一个交易日 2026-01-02 |
| 行情缺口 | 分别验证缺少 5m、事件前参考价和目标日线时的局部或整体降级 |
| 时间错位 | 发布日期与实际发布时间冲突时停止计算，且不会请求行情 |
| 未来数据 | `as_of` 只到事件后 10 分钟时，30m、1h、close 均为 `pending`；未来更新的分钟线被质量检查拒绝 |
| 基准数据缺失 | 单标的分钟或日线 Provider 失败不会中断其他标的；缺失窗口的基准差为不可用 |
| 分钟数据质量 | 重复分钟线和 `updated_at > as_of` 的分钟线均被拒绝 |

## 真实事件与数据来源

真实事件选用美国 2026 年 8 月 CPI。BLS 的归档发布页明确标注材料在 **2026-09-11 08:30 ET** 解禁，因此本次研究使用该分钟级官方发布锚点：

- [BLS Consumer Price Index News Release — August 2026](https://www.bls.gov/news.release/archives/cpi_09112026.htm)
- `release_id = cpi:2026-09-11`
- `release_at = 2026-09-11 08:30:00 America/New_York`
- `as_of = 2026-09-14 12:00:00 America/New_York`

这里的 `release_at` 表示官方发布的分钟级时间，不代表系统取得了逐秒或逐笔的实际发送时间。

行情来自 Longbridge，只读查询 NVDA、QQQ 和半导体行业杠杆 ETF SOXL。每个标的均取得 465 根 1m K 线；质量状态为 `usable`，要求检查的盘前 70 根、正常交易时段 390 根均完整观测，另外包含 16:00–16:05 的 5 根盘后 K 线。三只证券的目标正式收盘日线均可用且为原始价格口径。

## 真实 Market Reaction 结果

参考价采用 08:29–08:30 ET 完整分钟线的收盘价。下表收益率均相对该参考价计算，数值按输出保留三位小数：

| 标的 | 参考价 | T+5m | T+30m | T+1h | 正式收盘 |
| --- | ---: | ---: | ---: | ---: | ---: |
| NVDA | 219.747 | -0.077% | +0.742% | +0.702% | -0.663% |
| QQQ | 714.800 | -0.147% | +0.291% | +0.129% | +0.011% |
| SOXL | 119.950 | -0.700% | +1.459% | +0.684% | +1.559% |

四个窗口共 12 个观察结果全部为 `usable`，且没有 Market Reaction issue。

相对 QQQ 的收益率差，单位为百分点：

| 对比 | T+5m | T+30m | T+1h | 正式收盘 |
| --- | ---: | ---: | ---: | ---: |
| NVDA − QQQ | +0.070 | +0.451 | +0.573 | -0.674 |
| SOXL − QQQ | -0.553 | +1.168 | +0.555 | +1.548 |

这些结果只描述同一观察窗口内实际发生的价格变化，不证明 CPI 发布导致了对应涨跌。

## 复现命令

检查真实分钟行情覆盖和正式收盘日线：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_day30_longbridge_market.py
```

执行真实 CPI 端到端计算：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_day30_real_market_reaction.py
```

第二个脚本会严格要求三只证券的 5m、30m、1h 和 close 全部为 `usable`，否则以失败状态退出。

## 已知限制

- 真实脚本依赖本地 Longbridge 凭据、行情权限及供应商历史数据保留范围，不加入默认离线测试；
- 本次只核实官方发布时间与行情反应，没有把 CPI Actual、Consensus 或 Estimated Surprise 放入端到端输入；
- 一分钟 OHLC 无法还原宏观消息发布瞬间的逐笔价格路径；
- SOXL 是杠杆 ETF，其相对 QQQ 的结果不能解释为无杠杆行业基准；
- Market Reaction 仍是独立确定性模块，与 Decision Engine 和 Agent 的组合属于 D31–D35。
