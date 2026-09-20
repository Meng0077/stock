# D15：按需公司索引与进程内复用

2026-09-19：Day15 主体已完成，精确 block/XPath 对外回查作为遗留项。首次查询未预置 ticker 时，系统会从 SEC 获取截至 `as_of` 已公开的必要 filing，解析、分段、嵌入并建立内存向量索引；同一进程内的后续查询复用时间边界兼容且配置相同的索引。Agent 继续调用通用的 `retrieve_knowledge(company_id, question)`，无需为公司增加工具或白名单。

## 当前流程

```text
retrieve_knowledge(company_id, question)
        +
ResearchContext.as_of
        ↓
ensure_company_index()
        ↓
查找 company_id、config_id 相同且 state.as_of <= request.as_of 的最新状态
        ├─ 找到 → 复用 InMemoryVectorStore
        └─ 未找到
             ↓
         SEC filings
             ↓
         FilingDocument[]
             ↓
         DocumentChunk[]
             ↓
         Embedding
             ↓
         InMemoryVectorStore + CompanyIndexState
        ↓
similarity_search(question)
        ↓
带来源 URL 和 data_mode 的证据
```

`as_of` 是资料时间边界，不要求与索引建立时间完全相等。较晚请求可以复用较早索引；较早的历史请求不能复用未来索引。省略 `as_of` 时复用该公司当前配置的最新进程内索引，没有索引时使用当前 UTC 时间建立。Day15 尚不主动检查索引建立后是否出现新 filing；freshness 和增量更新属于 Day17。

## 索引身份

`CompanyIndexState` 以 `company_id + as_of + config_id` 保存。查找时使用满足时间边界的最新状态，状态中保留文档版本、chunk 数量和向量库。

`config_id` 是以下配置的稳定 SHA-256 指纹：

```text
parser_version = sec-html-v1
chunk_size = 800
chunk_overlap = 100
embedding_model = sentence-transformers/all-mpnet-base-v2
```

`parser_version` 表示 SEC HTML 到 `FilingDocument` 的解析规则版本。解析规则发生实质变化时递增该版本，`config_id` 随之变化，旧索引不会被继续复用。`document_id + content_hash` 标识具体 filing 文件及其解析后内容版本；chunk ID 还包含分段配置和 chunk 序号。

## 检索证据

`retrieve_knowledge` 返回：

```python
{
    "evidence_id": "rag:...",
    "company_id": "AMD",
    "source": "https://www.sec.gov/Archives/...",
    "content": "...",
    "data_mode": "historical",
}
```

当前调用方可以通过 `source` 打开 SEC 原始文件，并使用返回的 `content` 核对片段。Day14 生成的 block、字符范围和 XPath 仍保存在内部文档与 chunk metadata 中，但 Day15 的公开检索结果暂不返回这些字段；精确到 block/XPath 的回查接口继续作为遗留项。

## data_mode

三层 data mode 使用不同类型和语义：

```text
RequestDataMode
→ 本次运行允许使用的资料模式

EvidenceDataMode
→ 单条工具证据实际属于 fixture / historical / live，不允许 mixed

OutputDataMode
→ 最终回答实际引用证据的聚合模式
```

API 当前使用 `RequestDataMode=mixed`，允许 Agent 组合不同模式；指定 `fixture`、`historical` 或 `live` 时，本轮成功工具证据只能使用对应模式。教学报价和公司简介证据为 `fixture`，SEC filing 证据为 `historical`。

最终 `ResearchOutput.data_mode` 按实际引用的证据校验：

- 只引用一种模式：输出该模式；
- 同时引用不同模式：输出 `mixed`；
- 没有引用证据：输出 `null`。

`data_mode` 字段仍然必填；`null` 必须由模型显式输出，不能通过缺少字段表示。单条证据只能是 `fixture`、`historical` 或 `live`，不能是 `mixed`。程序会拒绝本轮工具没有提供的 evidence ID、请求策略不允许的证据模式、与实际引用证据不一致的最终模式，以及同一个 evidence ID 对应不同模式的冲突。

## SEC 请求策略

SEC 请求统一经过 `documents/sec_http.py`：复用同一个 `httpx.Client`，进程内最多每秒发起 3 个请求；对 429、500、502、503、504 以及连接、读取和协议临时错误最多重试 3 次。重试采用指数退避并优先遵守 `Retry-After`。代理最终失败映射为 `SecProxyUnavailableError`，SEC 503 最终失败映射为 `SecServiceUnavailableError`。

## 运行与验证

在项目根目录运行固定测试：

```bash
backend/.venv/bin/python -m pytest -c backend/pyproject.toml
```

验证进程内复用、配置变化和时间边界：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python evals/verify_index_reuse.py
```

真实 SEC + 本地 embedding 验收：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python evals/verify_lazy_company_index.py
```

固定验收覆盖首次构建、相同配置复用、解析/分段/embedding 配置变化、较晚 `as_of` 复用、历史 `as_of` 隔离、稳定证据 ID、原文 URL 和 historical data mode。真实 AMD 验证已确认首次建库后第二次查询复用同一个索引。

## Day15 边界

- 索引只保存在当前 Python 进程；重启复用和数据库持久化属于 Day16。
- 复用旧索引前检查新 filing、只处理新增或修订文件属于 Day17。
- 当前 embedding 配置记录模型名；revision 和向量维度随持久化设计在 Day16 补齐。
- 精确到 block、字符范围和 XPath 的对外回查接口尚未完成。
- 当前检索只证明返回了可定位证据；句子是否被证据充分支持仍需独立评估，不能只检查 evidence ID 是否存在。
