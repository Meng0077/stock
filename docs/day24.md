# Day24：CPI/PPI 发布事件

Day24 接入 BLS 已发布的 CPI/PPI 数据，并通过 FRED API 获取官方发布日期。主路径面向“最近一次宏观数据发布”，不承担严格历史回测，也不在缺少可靠来源时补造精确发布时间。

```text
BLS Public Data API
        ↓
BLSSeriesPoint(period, value)
        ↓
InflationReading(actual, previous)

FRED API
        ↓
Series -> Economic Release -> Release Dates

Trading Economics Calendar（可选）
        ↓
consensus + scheduled_release_at

        ↓
MacroReleaseEvent
        ├── release_date
        ├── scheduled_release_at
        ├── released_at
        └── metrics
```

## 时间字段

| 字段 | 含义 |
|---|---|
| `period` | 指标描述的统计月份，例如 2026-08 CPI |
| `release_date` | FRED 返回的官方发布日期，只精确到日期 |
| `scheduled_release_at` | Trading Economics 日历中的计划发布时间 |
| `released_at` | 已确认的真实发布时间；当前没有可靠来源时为 `None` |

FRED 的发布日期不会被转换成午夜，也不会自行补成 08:30 ET。`period_binding="latest_assumed"` 明确表示当前使用“最近发布日期 + 最新 observation”的在线研究绑定规则。

## 发布事件

CPI Release 包含：

- CPI MoM / YoY；
- Core CPI MoM / YoY。

PPI Release 包含：

- PPI MoM / YoY；
- Core PPI MoM / YoY。

`MacroSnapshot.recent_releases` 保存事件，避免 Agent 自己把四项指标拼成一次发布。稳定事件 ID 使用 `release_type:release_date`，例如 `cpi:2026-09-11`。

## Consensus 与 Surprise

Trading Economics 的 `Forecast` 是可选数据。没有匹配的 indicator、measure 和 period 时：

```text
consensus = None
surprise = None
```

普通 Calendar 响应不能证明 Forecast 属于公布前的历史快照，因此 `forecast_as_of=None`、`consensus_pit_verified=False`。只有能够确认 Forecast 在正式发布时间之前已经存在时才计算 Surprise。

BLS 普通时间序列 API 可能返回后续修订值，因此即使 `release_date` 已知，`actual_pit_status` 仍保持 `unverified`。

## Provider 边界

- `BLSProvider`：只读取 BLS 原始时间序列，不保存发布日期；
- `FredProvider`：提供 Series 对应的 Release 和发布日期；
- `TradingEconomicsConsensusProvider`：提供可选 Consensus 和计划发布时间；
- `MacroSnapshotBuilder`：调用 Provider 和纯计算函数，将指标组织成发布事件；
- 单个 Provider 的领域错误只影响对应模块，并写入 `warnings`；编程错误不被吞掉。

BLS ICS 在当前运行环境中会被网关拒绝，因此不进入主链路，也不通过伪装浏览器 User-Agent 绕过。

## 验收

离线测试：

```bash
cd backend
.venv/bin/pytest -q -p no:cacheprovider \
  tests/test_bls_provider.py \
  tests/test_fred_release_dates.py \
  tests/test_te_consensus_provider.py \
  tests/test_macro_inflation_snapshot.py \
  tests/test_macro_releases.py \
  tests/test_macro_builder.py
```

在线验收需要在 `backend/.env` 设置 `FRED_API_KEY`。`TRADING_ECONOMICS_API_KEY` 可选；未设置时脚本同时验证“缺少预期值不计算 Surprise”。

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_day24_macro.py
```

Day24 不实现分钟级市场反应、严格历史 vintage 回放或 MarketReaction；这些能力需要可靠的事件时间和盘中市场数据。

2026-09-24 已完成真实在线验收：CPI 发布日为 2026-09-11，PPI 发布日为 2026-09-10，两次 Release 均生成 4 项指标。当前环境未配置 Trading Economics key，因此计划发布时间和 Consensus 保持缺失，未计算 Surprise。


flowchart TD

    A[用户问题 / Agent 需要宏观上下文] --> B[MacroSnapshotBuilder.build_latest(as_of)]

    %% ======================
    %% CPI / PPI
    %% ======================
    B --> C1[构建 CPI Release]
    B --> C2[构建 PPI Release]

    C1 --> D1[FRED Provider\nget_series_release + get_release_dates\n拿到 release_date]
    C1 --> D2[BLS Provider\nfetch_series\n拿到 CPI/Core CPI 原始指数]
    C1 --> D3[TE Consensus Provider\nget_consensus\n拿到一致预期]

    D2 --> E1[calculate_inflation_reading\n算出 MoM / YoY / previous]
    D3 --> E2[find_release_consensus\n按 indicator + measure + period + release_date 匹配预期]
    D1 --> F1[release_date]
    E1 --> G1[build_inflation_metrics]
    E2 --> G1
    F1 --> G1

    G1 --> H1[MacroMetricSnapshot\nCPI MoM / CPI YoY / Core CPI MoM / Core CPI YoY]
    H1 --> I1[build_macro_release]
    F1 --> I1
    D3 --> J1[resolve_scheduled_release_at\n尝试取计划发布时间]
    J1 --> I1
    I1 --> K1[MacroReleaseEvent\nrelease_type = cpi]

    C2 --> D4[FRED Provider\n拿到 PPI release_date]
    C2 --> D5[BLS Provider\n拿到 PPI/Core PPI 原始指数]
    C2 --> D6[TE Consensus Provider\n拿到一致预期]
    D5 --> E3[calculate_inflation_reading]
    D6 --> E4[find_release_consensus]
    D4 --> F2[release_date]
    E3 --> G2[build_inflation_metrics]
    E4 --> G2
    F2 --> G2
    G2 --> H2[MacroMetricSnapshot\nPPI MoM / PPI YoY / Core PPI MoM / Core PPI YoY]
    H2 --> I2[build_macro_release]
    F2 --> I2
    D6 --> J2[resolve_scheduled_release_at]
    J2 --> I2
    I2 --> K2[MacroReleaseEvent\nrelease_type = ppi]

    %% ======================
    %% PCE
    %% ======================
    B --> C3[构建 PCE Release]
    C3 --> D7[FRED Provider\nPCEPI -> release_date]
    C3 --> D8[BEA Provider\nfetch_indexes\n拿到 PCE/Core PCE 原始指数]
    C3 --> D9[TE Consensus Provider\n拿到一致预期]

    D8 --> E5[calculate_pce_reading\n算出 MoM / YoY / previous]
    D9 --> E6[find_release_consensus]
    D7 --> F3[release_date]
    E5 --> G3[build_inflation_metrics]
    E6 --> G3
    F3 --> G3
    G3 --> H3[MacroMetricSnapshot\nPCE MoM / PCE YoY / Core PCE MoM / Core PCE YoY]
    H3 --> I3[build_macro_release]
    F3 --> I3
    D9 --> J3[resolve_scheduled_release_at]
    J3 --> I3
    I3 --> K3[MacroReleaseEvent\nrelease_type = pce]

    %% ======================
    %% Employment
    %% ======================
    B --> C4[构建 Employment Situation Release]
    C4 --> D10[FRED Provider\nPAYEMS -> release_date]
    C4 --> D11[BLS Provider\nfetch_series\n拿到就业原始序列]
    C4 --> D12[TE Consensus Provider\n拿到一致预期]

    D11 --> E7[calculate_nonfarm_payrolls]
    D11 --> E8[calculate_unemployment_rate]
    D11 --> E9[calculate_average_hourly_earnings]

    E7 --> G4[employment_metric_to_snapshot]
    E8 --> G4
    E9 --> G4

    D12 --> E10[merge_consensus / find_release_consensus]
    G4 --> H4[MacroMetricSnapshot\nNFP / Unemployment / AHE]
    E10 --> H4

    H4 --> I4[build_macro_release]
    D10 --> I4
    D12 --> J4[resolve_scheduled_release_at]
    J4 --> I4
    I4 --> K4[MacroReleaseEvent\nrelease_type = employment_situation]

    %% ======================
    %% Weekly Claims
    %% ======================
    B --> C5[构建 Weekly Claims Release]
    C5 --> D13[FRED / WeeklyClaims Provider\n拿到 Initial / Continuing / 4W Avg]
    C5 --> D14[TE Consensus Provider\n拿到一致预期]
    D13 --> E11[build weekly claims metrics]
    D14 --> E12[merge_consensus]
    E11 --> H5[MacroMetricSnapshot\nInitial Claims / Continuing Claims / 4W Avg]
    E12 --> H5
    H5 --> I5[build_macro_release]
    I5 --> K5[MacroReleaseEvent\nrelease_type = weekly_claims]

    %% ======================
    %% Fed / Treasury
    %% ======================
    B --> C6[FedDataProvider\nget_target_ranges]
    B --> C7[FedDataProvider\nget_projections]
    B --> C8[TreasuryRatesProvider\nget_snapshot]

    C6 --> L1[FedPolicySnapshot]
    C7 --> L2[FedMedianProjection[]]
    C8 --> L3[TreasurySnapshot\n3M / 2Y / 10Y / 30Y / spreads]

    %% ======================
    %% Final Snapshot
    %% ======================
    K1 --> M[MacroSnapshot]
    K2 --> M
    K3 --> M
    K4 --> M
    K5 --> M
    L1 --> M
    L2 --> M
    L3 --> M

    B --> N[warnings[]\n如 provider unavailable / stale / missing]
    N --> M

    M --> O[Agent / 上层分析逻辑]
