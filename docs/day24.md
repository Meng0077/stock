# Day24：基于发布事件的宏观数据模块

Day24 接入 CPI、PPI、PCE、就业、周度失业金申领、Fed Policy、SEP 和美债收益率。长桥是普通在线研究的宏观发布主路径，BLS、BEA 和 FRED 保留为发布数据回退，Fed Policy、SEP 与美债继续由 FRED 提供。主路径面向“最近一次宏观数据发布”，不承担严格历史回测，也不在缺少可靠来源时补造精确发布时间。

```text
Longbridge Macro             发布前 Forecast 快照
        │                              │
        ├── Actual / Previous          └── captured_at + Consensus
        ├── Forecast                              │
        └── Scheduled Time                        │
                         ↓                        ↓
                      MacroReleaseEvent
                              ↓
       FRED Fed Policy / SEP + Treasury Yield Curve
                              ↓
                         MacroSnapshot
```

## 时间字段

| 字段 | 含义 |
|---|---|
| `period` | 指标描述的统计月份，例如 2026-08 CPI |
| `release_date` | 长桥事件日期；官方回退路径使用 FRED 发布日期 |
| `scheduled_release_at` | 长桥记录中的计划发布时间 |
| `released_at` | 已确认的真实发布时间；当前没有可靠来源时为 `None` |

长桥时间不会冒充经独立核实的实际发布时间。`period_binding="latest_assumed"` 明确表示当前使用供应商内部事件与统计期的在线研究绑定规则。

## 发布事件

CPI Release 包含：

- CPI MoM / YoY；
- Core CPI MoM / YoY。

PPI Release 包含：

- PPI MoM / YoY；
- Core PPI MoM / YoY。

此外还包括：

- PCE / Core PCE MoM、YoY；
- Nonfarm Payrolls、Unemployment Rate、Average Hourly Earnings MoM；
- Initial Claims、Continuing Claims、Initial Claims 4-week Average；
- 当前与前次 Fed 目标利率区间、SEP 中位数预测；
- 3M、2Y、10Y、30Y 美债收益率、日变化和期限利差。

`MacroSnapshot.recent_releases` 保存事件，避免 Agent 自己把四项指标拼成一次发布。稳定事件 ID 使用 `release_type:release_date`，例如 `cpi:2026-09-11`。

## Consensus 与 Surprise

长桥历史记录可以提供 Forecast，但只有项目在发布前实际保存的快照才用于计算 Estimated Surprise。没有匹配的 indicator、measure 和 period 时：

```text
consensus = None
estimated_surprise = None
```

定期执行 `evals/capture_macro_forecasts.py` 会追加保存下一次 CPI、PPI、PCE、Employment Situation 和 Weekly Claims 的 Forecast。发布后，`MacroSnapshotBuilder` 按 release type、release date、indicator、measure、period 和 unit 精确匹配，并计算：

```text
estimated_surprise = actual - pre_release_forecast
```

快照记录 `forecast_as_of` 和 `consensus_source="longbridge"`。由于实际发布时间和 Actual 初始版本尚未严格验证，`consensus_pit_verified=False`、`surprise=None`，不会把 Estimated Surprise 冒充为严格 PIT Surprise。

BLS 普通时间序列 API 可能返回后续修订值，因此即使 `release_date` 已知，`actual_pit_status` 仍保持 `unverified`。

## Provider 边界

- `LongbridgeMacroProvider`：提供发布事件的 Actual、Previous、Forecast 和计划时间；
- `BLSProvider`、`BEAPCEProvider`、`FredProvider`：长桥发布无法形成事件时的官方回退；
- `WeeklyClaimsProvider`：通过统一的 `FredProvider` 读取带日期级 vintage 的 Claims 序列；
- `capture_next_forecasts`：只采集尚未发布事件的 Forecast；
- `append_forecast_snapshot`：将发布前快照追加到 JSONL，不覆盖历史版本；
- `match_release_forecasts`：发布后匹配快照并生成 Estimated Surprise；
- `FedDataProvider`：读取目标利率区间和 SEP 中位数预测；
- `TreasuryRatesProvider`：读取四个期限的日度名义收益率；
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
  tests/test_macro_*.py
```

在线验收需要在 `backend/.env` 设置长桥、FRED 和 BEA 密钥。Forecast 文件默认位于 `evals/results/macro_forecasts.jsonl`，可通过 `MACRO_FORECAST_SNAPSHOTS_PATH` 修改。

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/capture_macro_forecasts.py

PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_day24_macro.py

PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_macro_agent.py
```

采集命令每次只执行一轮；部署时由外部调度器定期调用。重复采集会保留多个时间版本，匹配时选择发布前最后一次有效快照。

## 当前仍未完成

- 长桥事件时间尚未独立核实为真实发布时间，`released_at` 仍为空。发布日期当天会保守跳过该事件，不能用于分钟级 Market Reaction；
- 长桥历史 Actual 可能包含后续修订，`actual_pit_status` 保持 `unverified`，尚不支持严格历史 vintage 回放；
- 当前输出的是有发布前采集证据的 Estimated Surprise，不是严格 PIT Surprise；

Day24 不实现分钟级市场反应或 MarketReaction；这些能力进入 D26–D30，并要求可靠的事件时间和盘中市场数据。

## Agent Tool 接入

LangChain Agent 已注册只读 `get_macro_snapshot` Tool：

- 不传 `release_type` 时返回截至任务 `as_of` 的完整 `MacroSnapshot`，包括最近发布、Fed Policy、SEP、美债和数据质量警告；
- 传入 `cpi`、`ppi`、`pce`、`employment_situation` 或 `weekly_claims` 时，只返回最近一次对应 `MacroReleaseEvent`；
- Tool 从运行时上下文取得延迟创建的 `MacroSnapshotBuilder`；Tool 模块不读取密钥或配置 Provider，真实 Provider 由 API 依赖在首次宏观调用时创建；
- 完整快照和单个发布都会生成 `macro:*` evidence ID，并进入现有结构化输出与 evidence 校验；
- Agent 提示词要求保留 `consensus`、`estimated_surprise`、`surprise` 的原始语义，不得把 Estimated Surprise 表述为严格历史 Surprise。

普通工具继续使用 30 秒执行上限。真实宏观快照需要组合多个 Provider，Macro Tool 单独使用 90 秒执行上限；这只是 Agent 调用边界，不改变各 Provider 已有的请求和重试策略。

2026-09-26 已完成真实 API 端到端验收：MacroSnapshot 包含 CPI、PPI、PCE、Employment Situation、Weekly Claims、Fed Policy、5 项 SEP 中位数预测和完整美债曲线。长桥发布分别生成 4、4、4、3、3 项指标；美债曲线观测日为 2026-09-24。

同日已完成真实模型 Agent 联调：模型请求 `get_macro_snapshot`，Tool 使用真实 Provider 返回最近一次 CPI，`macro:cpi:2026-09-11` evidence 通过结构化输出校验，运行终态为 `completed`。可通过 `evals/verify_macro_agent.py` 重复验收；脚本只打印状态、工具事件和 evidence ID，不打印密钥或完整供应商响应。

以下流程图描述长桥不可用时的官方 Provider 回退链路。


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
