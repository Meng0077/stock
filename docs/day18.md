# Day18：Financial Tool 与工具边界

## 目标

Day18 把精确财务数值从文档 RAG 中拆出，建立四类独立能力边界。

| 能力 | 当前实现 | Day18 状态 |
|---|---|---|
| Market Tool | 本地 fixture 报价 | 保留，真实行情由 Day21–D25 接入 |
| Financial Tool | SEC Company Facts | 已接入 |
| Knowledge Tool | SEC filing + RAG | 已接入 |
| News/Search Tool | 尚未接入 | 明确返回能力不足，Day26–D30 处理 |

精确收入、净利润、资产等数值使用 Financial Tool。管理层解释、业务变化和风险因素使用 Knowledge Tool。Agent 可以在同一个回答中组合两类证据。

## Financial 数据流

```text
ticker
  ↓ ticker_to_cik()
CIK
  ↓ SEC Company Facts
原始 XBRL entries
  ↓ parse_financial_facts()
FinancialFact[]
  ↓ PostgreSQL Numeric
financial_facts
  ↓ period / as_of 过滤
get_financial_facts
  ↓
financial:* evidence_id
```

`FinancialFact` 保留：

- Decimal 数值与单位；
- start / end 报告期间；
- filed date；
- form、accession number；
- fiscal year、fiscal period 和 frame。

数据库中的 `value` 使用 PostgreSQL `NUMERIC`，避免用浮点数保存精确财务数值。

## 缓存与时间边界

`financial_fact_syncs` 按以下身份保存同步状态：

```text
company_id + concept + unit
```

查询流程为：

```text
检查 sync state
  ├─ covered_through >= as_of → 直接查询 PostgreSQL
  └─ 覆盖不足 → 通过统一 SEC HTTP 层下载、解析、保存并更新 sync state
```

查询只返回 `filed_date <= as_of` 的事实。同一报告期间有多个披露版本时，返回截至 `as_of` 已知的最新版本。

## Evidence 校验

Financial Tool 返回：

```json
{
  "data_mode": "historical",
  "facts": [
    {
      "evidence_id": "financial:...",
      "company_id": "NVDA",
      "concept": "NetIncomeLoss",
      "value": "...",
      "unit": "USD"
    }
  ]
}
```

最终回答的每个 `financial:*` ID 必须同时满足：

1. 由本轮 Financial Tool 返回；
2. 能从 PostgreSQL 解析回原始 `FinancialFact`；
3. evidence 的模式符合请求策略；
4. 最终 `ResearchOutput.data_mode` 与实际引用证据一致。

Financial 与 RAG evidence 都属于 historical，因此同时引用两者时，最终模式仍是 `historical`，不是 `mixed`。

## 验收

运行全部离线测试：

```bash
cd backend
.venv/bin/python -m pytest -q
```

验证 Financial Facts 首次保存与跨进程复用：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_financial_persistence.py --phase seed

PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_financial_persistence.py --phase reuse
```

验证 Agent 同时调用 Financial 与 Knowledge Tool：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_tools.py
```

最后一个脚本会调用真实模型、SEC 和 PostgreSQL，不属于离线测试。

## 已存在数据库的迁移

如果 `financial_facts.value` 曾以 `double precision` 创建，`create_all()` 不会自动修改已有列。执行一次：

```sql
ALTER TABLE financial_facts
ALTER COLUMN value TYPE NUMERIC
USING value::numeric;
```

新数据库直接按当前 SQLAlchemy metadata 创建为 `NUMERIC`。

## 当前边界

- Company Facts 当前按 XBRL concept 和 unit 查询，不负责把任意自然语言自动映射成所有可能的财务口径。
- quarterly / annual 通过 form 与期间长度区分，不计算同比、环比或 TTM。
- Company Facts 只有 filed date，因此历史边界精确到日期，不精确到 filing accepted time。
- 真实市场数据与新闻不属于 Day18。
