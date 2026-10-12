# Day37：Company Registry 与 Target Resolver

## 完成结论

Day37 的 Company Registry 与 Target Resolver 核心能力已经完成，可以进入 D38 的 Workflow 接入阶段。

当前完成的是：

```text
User Message
  ↓
Explicit Ticker + Known Alias
  ↓
Security Registry Verify
  ↓
Coverage Check
  ↓ 必要时
LLM Semantic Resolution
  ↓
Security Registry Verify
  ↓
resolved / ambiguous / unresolved / absent
```

Day37 的完成范围不包含 Graph 接入。Resolver 放到 Planner 之前、`interrupt()` 和 resume 澄清流程已在 D38 实现，见 [`docs/day38.md`](day38.md)。

## Company Registry

`backend/src/stock_agent/company/registry.py` 提供统一证券身份查询：

- SEC `company_tickers.json` 是公司 ticker、名称与 CIK 的确定性来源；
- SEC 未覆盖的证券可以使用具备 `get_security_info()` 的行情 Provider 验证；
- SEC 命中时保留十位 CIK；
- 行情 Provider 命中时返回 ticker 与名称，CIK 保持 `None`；
- Provider 失败与“证券不存在”保持不同错误语义。

原有 `documents.sec_provider.ticker_to_cik()` 已改为复用 Company Registry，因此 SEC Documents、Financial、Knowledge 和 Company Profile 继续使用原入口，但不再各自下载和解析 ticker 映射。

Longbridge Provider 新增只读 `get_security_info()`，通过 `static_info()` 验证 SEC 未覆盖的 ETF 等证券。Mapper 只保留系统需要的标准 ticker 与英文名称。

## Alias 与显式 ticker

确定性解析会扫描完整消息：

- 裸 ticker 使用大写作为强信号；
- `$NVDA`、`$nvda` 支持 cashtag；
- 支持 `BRK.B`、`BRK-B` 形式；
- Alias 覆盖高频中英文名称和明确昵称；
- 同一实体可能对应多个 share class，例如 Google 对应 `GOOG / GOOGL`；
- 显式 ticker 与 Alias 合并、按原文位置排序并去重，不会命中一个标的后提前停止。

所有候选 ticker 必须经过 Registry。类似 `CPI` 的大写 token 即使被词法扫描发现，也不能未经验证进入研究请求。

## Coverage Check 与 LLM 边界

以下情况才进入语义模型：

- 没有 deterministic mention；
- Registry 拒绝了某个 mention；
- Alias 对应多个证券；
- 裸 ticker 同时具有明显普通语言含义，例如 `AI`；
- 句子存在比较或并列信号，但只识别出不足两个标的。

模型只判断自然语言指代并给出 candidate，不负责验证证券真实性。输入会包含 deterministic mentions、已验证标的、歧义候选、被拒绝 mention 和当前关注 mention。模型新增或缩小后的 ticker 必须再次经过 Registry；无效 candidate 会进入 `unresolved`，不能进入 `resolved_targets`。

## TargetResolution

Resolver 保留三类事实：

| 字段 | 含义 |
| --- | --- |
| `resolved_targets` | 已唯一确定并经过 Registry 验证的 ticker |
| `ambiguous_targets` | 已确认是证券指代，但仍有多个候选 |
| `unresolved_mentions` | 已知在指证券，但无法可靠确定 ticker 的原文表达 |

当前最终状态包含四种；多个已确认 ticker 也属于 `resolved`：

| 状态 | 条件 |
| --- | --- |
| `resolved` | 一个或多个 ticker 已确定，且没有歧义或未解决表达 |
| `ambiguous` | 至少有一个多候选实体 |
| `unresolved` | 已确认存在证券指代，但无法可靠确定 ticker |
| `absent` | 整句话没有证券指代，例如纯宏观问题 |

`unresolved` 优先级最高，其次是 `ambiguous`。系统不会因为已经识别出一个 ticker，就忽略同一句中仍未解决的另一个标的。

## 测试覆盖

新增测试覆盖：

- SEC 官方 `cik_str` payload 转换、ticker 规范化与 CIK 补零；
- SEC 命中时不调用行情 fallback；
- SEC 未覆盖证券使用行情 Provider 验证；
- Provider 失败不会伪装成 unknown ticker；
- 旧 `ticker_to_cik()` 复用 Company Registry；
- Longbridge static info 映射、无结果和 Provider 异常；
- 中文 Alias 的单标的解析；
- 纯 ticker、英文 Alias 与投资社区昵称均走确定性解析，不调用模型；
- Alias mention 保留用户消息中的原始文本；
- 显式 ticker + Alias 的多标的解析；
- `CPI` 被拒绝但 `NVDA` 保留；
- Google 两类股票保持 ambiguous；
- 长尾实体由 LLM 给出 candidate 后再次经过 Registry；
- 无效 LLM candidate 进入 unresolved；
- `AI` 普通语义不会覆盖真实 NVDA；
- 没有证券指代时明确 absent；
- 已确认一个 ticker 但第二个标的无法确认时，保留已确认结果并返回 unresolved，不静默开始单股研究；
- 共享 Chat Model 与 Agent 的测试缓存相互隔离。

运行 Company 专项与关联回归：

```bash
backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  -c backend/pyproject.toml \
  backend/tests/test_company_registry.py \
  backend/tests/test_company_resolver.py \
  backend/tests/test_longbridge_market.py \
  backend/tests/test_sec_provider.py \
  backend/tests/test_financial.py \
  backend/tests/test_langgraph_day36.py
```

运行类型检查：

```bash
backend/.venv/bin/pyright \
  backend/src/stock_agent/company \
  backend/src/stock_agent/documents/sec_provider.py \
  backend/src/stock_agent/api/dependencies.py \
  backend/src/stock_agent/agents/langgraph/graph.py \
  backend/tests/test_company_registry.py \
  backend/tests/test_company_resolver.py
```

2026-10-09 验收结果：

- Company 专项与关联回归：`65 passed`；
- Company / SEC / API 依赖 / Graph 相关 Pyright：`0 errors`；
- 完整后端：`629 passed`；
- `git diff --check HEAD`：通过。

## 当前边界与后续状态

Day37 当时没有实现多股票研究。D38 已将 Resolver 接入 LangGraph 起点和 `/api/research`；D39 开始把正式请求升级为 `company_ids`，多个已验证 ticker 统一作为 `resolved` 进入按证券分组的研究流程，`ambiguous / unresolved` 仍保留候选并中断澄清。恢复当前使用进程内存 Checkpoint；完整迁移状态与已知问题见 [`docs/day39.md`](day39.md)。

LLM fallback 当前由离线结构化模型测试覆盖，尚未记录真实模型专项联调。D38 的具体 Graph 和 API 验收见 [`docs/day38.md`](day38.md)。
