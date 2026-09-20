现在的核心原则是：

> 请求决定“允许使用什么数据”；Provider 决定“证据实际是什么数据”；最终引用决定“回答实际基于什么数据”。

### 1. 三种 `data_mode` 类型

在 [research_output.py](/Users/yangmeng/Desktop/interview/stock/backend/src/stock_agent/schemas/research_output.py) 中拆成了三层：

```python
EvidenceDataMode = Literal[
    "fixture",
    "historical",
    "live",
]

RequestDataMode = Literal[
    "fixture",
    "historical",
    "live",
    "mixed",
]

OutputDataMode = Literal[
    "fixture",
    "historical",
    "live",
    "mixed",
]
```

它们的含义不同：

| 类型 | 含义 | 是否允许 `mixed` |
|---|---|---:|
| `RequestDataMode` | 本次运行允许使用哪些数据环境 | 是 |
| `EvidenceDataMode` | 单条证据实际属于什么数据 | 否 |
| `OutputDataMode` | 最终回答实际引用了什么数据 | 是 |

### 2. Request 模式是访问策略

例如：

```python
ResearchRequest(
    data_mode="historical",
)
```

表示本轮只允许成功工具返回 `historical` 证据。

如果工具返回：

```json
{
  "evidence_id": "E1",
  "data_mode": "fixture"
}
```

即使模型最终没有引用 `E1`，本次运行仍会失败，因为模型已经接触到了请求策略不允许的数据。

当前规则是：

```text
request=fixture
→ 只允许 fixture 工具证据

request=historical
→ 只允许 historical 工具证据

request=live
→ 只允许 live 工具证据

request=mixed
→ 允许 fixture / historical / live 组合
```

API 当前使用 `mixed`，因为目前一次问题可能同时调用：

```text
fixture 教学报价
+
historical SEC 文档
```

### 3. Evidence 模式由 Provider 决定

请求参数不会改变数据本身的性质。

当前三个工具分别是：

```text
get_quote
→ fixture

get_company_profile
→ fixture

retrieve_knowledge
→ historical
```

例如 [knowledge.py](/Users/yangmeng/Desktop/interview/stock/backend/src/stock_agent/retrieval/knowledge.py) 固定返回：

```python
{
    "evidence_id": ...,
    "data_mode": "historical",
}
```

因为当前知识库资料来自 SEC filing。即使请求是：

```python
data_mode="fixture"
```

也不会把 SEC 证据改写成 `fixture`，而是被请求策略拒绝。

所以不用把 `data_mode` 一路传给：

```text
retrieve_knowledge()
→ ensure_company_index()
→ SEC Provider
```

这些底层函数负责返回真实的数据性质，不应由上层请求覆盖。

### 4. 单条证据不能是 `mixed`

下面这种结果现在会直接失败：

```json
{
  "evidence_id": "E1",
  "data_mode": "mixed"
}
```

因为单条证据必须明确属于：

```text
fixture
historical
live
```

`mixed` 只表示最终回答引用了多种证据模式。

---

## 最终 `ResearchOutput.data_mode` 如何确定

模型仍然需要填写 `data_mode`，但程序不会直接相信它。

程序会读取最终 `facts` 和 `inferences` 引用的所有 `evidence_ids`，然后查找每条证据对应的模式。

### 只引用 fixture

```python
facts = [
    EvidenceClaim(
        text="NVDA 教学报价为 100 USD",
        evidence_ids=["E-quote"],
    )
]
```

映射关系：

```text
E-quote → fixture
```

最终必须是：

```python
output.data_mode == "fixture"
```

### 只引用 SEC

```text
rag:... → historical
```

最终必须是：

```python
output.data_mode == "historical"
```

即使请求模式是：

```python
request.data_mode == "mixed"
```

最终也只是 `historical`，因为实际上只引用了历史资料。

### 同时引用报价和 SEC

```text
E-quote → fixture
rag:... → historical
```

最终必须是：

```python
output.data_mode == "mixed"
```

### 没有引用证据

例如资料不足：

```python
ResearchOutput(
    status="insufficient_information",
    facts=[],
    inferences=[],
    missing_information=["没有找到相关资料"],
    data_mode=None,
)
```

此时必须是：

```python
data_mode=None
```

不能因为请求模式是 `mixed`，就输出：

```python
data_mode="mixed"
```

因为没有证据时，并没有“实际使用了多种数据”。

---

# `evidence_id` 当前逻辑

`evidence_id` 的作用是建立这条可验证链：

```text
回答中的事实
    ↓ evidence_ids
工具实际返回的证据
    ↓
证据的数据模式和来源
```

模型不能自己创造一个 ID，再声称它来自工具。

## 1. 报价和公司资料 ID

LangChain adapter 会给每次成功结果生成 UUID：

```python
"evidence_id": f"E-{uuid4().hex}"
```

例如：

```text
E-37440120c6c54a32ae99250c85125128
```

对应实现位于 [langchain_tools.py](/Users/yangmeng/Desktop/interview/stock/backend/src/stock_agent/agents/langchain/langchain_tools.py)。

这种 ID：

- 每次调用都会不同；
- 只用于标识当前运行中的这条工具证据；
- 不适合作为长期稳定的文档 ID。

## 2. RAG 证据 ID

RAG 使用：

```text
rag:{chunk_id}
```

而 `chunk_id` 由下面几部分组成：

```text
document_id
+
document_content_hash
+
chunk/index config ID
+
chunk index
```

大致是：

```text
rag:{document_id}:{content_hash}:{config_id}:chunk:{index}
```

对应实现位于 [chunking.py](/Users/yangmeng/Desktop/interview/stock/backend/src/stock_agent/retrieval/chunking.py)。

这意味着：

- 同一份文档；
- 内容没有变化；
- chunk 配置没有变化；
- chunk 位置没有变化；

生成的 `evidence_id` 就保持一致。

如果文档内容、解析版本、分段配置变化，ID 也会变化，避免旧引用错误指向新内容。

## 3. 哪些 ID 会进入允许集合

程序只从以下三个白名单工具的成功 `ToolMessage` 中收集：

```text
get_quote
get_company_profile
retrieve_knowledge
```

必须同时满足：

```text
是 ToolMessage
+
工具名称在白名单
+
message.status == "success"
+
结果中确实存在 evidence_id
```

以下内容不会成为合法证据：

- 失败工具返回的 ID；
- 模型自己写出的 ID；
- `ResearchOutput` 结构化提交工具里的 ID；
- 非白名单工具返回的 ID；
- 不是合法 JSON 的 ToolMessage。

因此：

```text
ResearchOutput 工具
```

只负责提交最终结构，不是证据来源。

---

# 最终校验顺序

核心逻辑在 [structured_output.py](/Users/yangmeng/Desktop/interview/stock/backend/src/stock_agent/agents/structured_output.py)。

当前顺序是：

```text
1. 收集成功白名单工具提供的 evidence_id
2. 建立 evidence_id → EvidenceDataMode 映射
3. 检查模型引用的 ID 是否属于本轮
4. 检查每个被引用 ID 是否都有 data_mode
5. 检查本轮工具证据是否符合 RequestDataMode
6. 根据最终引用反推 OutputDataMode
7. 检查模型填写的 output.data_mode 是否正确
```

具体错误包括：

| 问题 | 内部错误 |
|---|---|
| 模型引用了本轮不存在的 ID | `unknown_evidence_id` |
| 证据没有合法模式 | `evidence_data_mode_missing` |
| 单条证据模式是 `mixed` 或其他非法值 | `evidence_data_mode_invalid` |
| 同一个 ID 一会儿是 fixture、一会儿是 historical | `evidence_data_mode_conflict` |
| 工具证据不符合请求策略 | `data_mode_not_allowed` |
| 最终输出模式与实际引用不一致 | `data_mode_mismatch` |

对外会收敛为：

```text
证据 ID / 模式本身有问题
→ invalid_evidence

请求策略或最终模式不一致
→ data_mode_mismatch
```

完整流程可以表示为：

```text
ResearchRequest.data_mode
        ↓
限制本轮允许使用的数据环境
        ↓
工具执行
        ↓
ToolMessage
├── evidence_id
└── EvidenceDataMode
        ↓
收集 allowed_ids 和 evidence_modes
        ↓
ResearchOutput
├── facts[].evidence_ids
├── inferences[].evidence_ids
└── data_mode
        ↓
根据实际引用反推 OutputDataMode
        ↓
校验模型填写结果
```

因此现在 `data_mode` 不再是模型随便声明的标签，而是由 `evidence_id → EvidenceDataMode` 的证据链约束出来的。
