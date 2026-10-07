# Day35：LangChain Agent 多维市场研究整合

## 目标

Day35 把 D31–D34 的确定性技术 Decision、D24 的宏观发布与 D26–D30 的 Market Reaction 交给同一个 LangChain Agent 编排：

```text
用户问题
    │
    ├─→ evaluate_market
    │      └─→ DecisionResult + Quote/Technical Evidence
    │
    ├─→ get_macro_snapshot
    │      └─→ MacroReleaseEvent + Macro Evidence
    │
    └─→ get_market_reaction
           └─→ MarketReactionResult + Reaction Evidence
                         │
                         ▼
                  ResearchOutput
```

代码继续负责取数、时间边界、数值计算、Guard、Decision 和 Reaction；LLM 只负责理解问题、选择工具、组织解释和提交结构化结果。

## `evaluate_market` Tool

Agent 只能传入 `company_id`，`as_of`、Market Provider 和市场状态由 `ResearchContext` 注入。Tool 内部流程为：

```text
Quote + completed daily Bars
          │
          ▼
build_guarded_market_analysis
          │
          ▼
MarketContext → evaluate_market → DecisionResult
```

返回值保留完整 `DecisionResult`，并把 Quote 和 Technical 作为两份独立 Evidence：

- `market:quote:<uuid>` 保留当前报价及其 data mode；
- `market:technical:<uuid>` 保留技术快照及历史 data mode；
- Quote Provider 失败时，如果完成日线可用，仍可以最近完成收盘价形成 Decision；
- Bars 不可用时，Technical 缺失，Decision 必须为 `blocked`，且不得携带方向性 Trace。

## `get_market_reaction` Tool

Agent 只能传入 `company_id` 和 `release_id`，不能传入 `event_at`、参考价、Provider 或 `as_of`。Tool 会使用受信任的 Macro Builder 重新查找当前 `as_of` 可用的发布事件，再调用已有 `research_event_reaction` Service。

关键边界：

- 未知或未发生的 `release_id` 返回 `reaction=null`，不生成 Evidence；
- Market Reaction 只需要发布事件的时间身份，不因宏观 metrics 为空而丢弃合法事件；
- 分钟行情能力不可用或 Provider 失败是结构化业务结果，不转换成 Tool exception；
- `pending` 表示观察窗口尚未形成，不等于 `missing`、0% 或已完成；
- 成功的反应证据 ID 固定为 `market-reaction:<release_id>:<symbol>`，data mode 为 historical。

## Agent 路由与解释约束

| 用户意图 | Tool 路由 |
| --- | --- |
| “NVDA 当前走势如何” | `evaluate_market` |
| “MA20 / RSI14 / ATR / 关键价位是多少” | `get_technical_analysis` |
| “最近一次 CPI 是多少” | `get_macro_snapshot` |
| “最近一次 CPI 后 NVDA 怎么走” | 先 `get_macro_snapshot`，取得具体 `release_id`，再 `get_market_reaction` |
| “当前走势如何，CPI 后又怎么走” | 第一轮并行 Technical Decision 和 Macro，第二轮 Reaction，第三轮 `ResearchOutput` |

System Prompt 明确限制：

- `DecisionResult.status == blocked` 时，不得自行补出 bullish、bearish、neutral 或 mixed；
- 不得重新计算或改写 Quote、MA/RSI/ATR、Macro 数值、Reaction 收益率和确定性 `market_view`；
- Market Reaction 只能描述事件前后已观察变化，不得把时间先后表述为已证明的因果；
- Technical Decision、Macro 和 Market Reaction 保持独立，不自行生成“综合上涨概率”、胜率或未定义的 confidence。

## 多维验收链路

Day35 的最终集成测试使用预置 Tool Calls 的 Fake Model 验证以下 DAG：

```text
Model Round 1
├─ evaluate_market(NVDA)
└─ get_macro_snapshot(cpi)

Model Round 2
└─ get_market_reaction(NVDA, cpi:2026-09-11)

Model Round 3
└─ ResearchOutput
```

该流程在现有 `MAX_MODEL_ROUNDS=3` 和 `MAX_TOOL_CALLS=4` 内完成。Macro Builder 调用两次：第一次生成 Macro Evidence，第二次由 Reaction Tool 按 `release_id` 重新确认受信任事件。这个重复查询是边界保护，不为了节省一次调用提前增加缓存抽象。

最终 `ResearchOutput` 独立引用：

- Macro 事实：`macro:<release_id>`；
- Market Reaction 事实：`market-reaction:<release_id>:<symbol>`；
- Technical Decision 分析结论：Quote 和 Technical 两份 Evidence。

## 代码位置

- `backend/src/stock_agent/agents/langchain/langchain_tools.py`：`evaluate_market` 和 `get_market_reaction` Tool；
- `backend/src/stock_agent/agents/langchain/langchain_agent.py`：Tool 路由、Guard 忠实性和非因果解释的 System Prompt；
- `backend/src/stock_agent/agents/evidence.py`：新 Tool 的 Evidence 白名单和 data mode 校验；
- `backend/src/stock_agent/schemas/tool_params.py`：Market Reaction 的只读参数契约；
- `backend/src/stock_agent/quality/market_service.py`：经过质量检查的 Quote 作为当前技术参考价；
- `backend/tests/test_langchain_tools.py`：Tool schema、正常、降级、未知/未来事件、失败和 pending 边界；
- `backend/tests/test_langchain_agent.py`：Prompt 契约、多工具 DAG、Evidence 维度和 blocked 流程。

## 已知限制

- Fake Model 的 Tool Calls 是预先设定的；集成测试证明 LangChain 多工具链路和 Evidence 契约正确，不证明任意真实模型都会聪明地选工具。
- `validate_evidence()` 校验 Evidence ID、可访问性和 data mode，不对自然语言做逐句语义判定；恶意或失误模型是否改写工具结论，留给 D41/D42 模型忠实度评估。
- Day35 不把 Macro 和 Market Reaction 隐式转换为技术方向或涨跌概率。

## 测试

Day35 及相关回归：

```bash
backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  backend/tests/test_decision_day31.py \
  backend/tests/test_decision_day32.py \
  backend/tests/test_decision_day33.py \
  backend/tests/test_decision_day34.py \
  backend/tests/test_langchain_tools.py \
  backend/tests/test_langchain_agent.py \
  backend/tests/test_evidence_validation.py \
  backend/tests/test_tool_params.py
```

完整后端：

```bash
backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  -c backend/pyproject.toml
```

## 完成情况

Day35 已于 2026-10-04 完成：

- `evaluate_market` 只读 Tool 及降级/blocked 边界已验收；
- `get_market_reaction` 只读 Tool 及时间、失败、pending 边界已验收；
- System Prompt 的问题路由、Guard、数值忠实性和非因果约束已锁定；
- 三轮多维研究链路与 blocked 流程已通过集成测试；
- D31–D35 相关回归：`152 passed`；
- 完整后端回归：`559 passed`；
- Day35 生产文件 Pyright：`0 errors`；
- `git diff --check HEAD`：通过。

下一步进入 D36：建立 LangGraph 状态与按需取数、检索、校验、分析和解释节点。

Day35 完成后又在相同 Agent/Evidence 边界上增加了 Earnings 8-K 披露后的 Market Reaction，但没有把该扩展误标为 D36。设计、时间限制与验收见 [`earnings-market-reaction.md`](earnings-market-reaction.md)。
