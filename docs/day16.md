# Day16：PostgreSQL + pgvector 持久化检索

## 目标

Day16 把 Day14 的 SEC 文档和 Day15 的 chunk、embedding 保存到 PostgreSQL，并让 `retrieve_knowledge()` 在进程重启后复用已有索引。

```text
SEC HTML
   ↓
FilingDocument
   ↓
filing_documents ──→ filing_blocks
   │
   └───────────────→ document_chunks
                         ↓
                   chunk_embeddings
                         ↓
              PostgreSQL + pgvector
                         ↑
                    query embedding
                         ↑
                retrieve_knowledge()
```

`company_indexes` 是索引完成标记。只有文档、block、chunk 和 embedding 都保存成功后，才写入该表。`ensure_company_index()` 会先查找符合 `company_id + as_of + index_config_id` 的记录；存在时直接复用，不再下载和重建 SEC 文档。

## 表和唯一标识

| 表 | 内容 | 唯一标识 |
| --- | --- | --- |
| `filing_documents` | SEC canonical document | `document_id + content_hash` |
| `filing_blocks` | 原文结构和 XPath | `block_id + document_content_hash` |
| `document_chunks` | RAG 检索单元和原文 offset | `chunk_id` |
| `chunk_embeddings` | chunk 对应向量及 embedding 元数据 | `chunk_id + index_config_id` |
| `company_indexes` | 某公司某时点的完整索引 | `company_id + as_of + index_config_id` |

`index_config_id` 由以下配置共同决定：

- `chunk_size`
- `chunk_overlap`
- `embedding_model`
- `embedding_revision`
- `embedding_dimension`
- `parser_version`

任何一项变化都会生成新的 `index_config_id`，避免复用由不同解析器、切分规则或 embedding 版本产生的向量。

当前默认 embedding 配置是：

```text
model: sentence-transformers/all-mpnet-base-v2
revision: e8c3b32edf5434bc2275fc9bab85f82640a19130
dimension: 768
normalize_embeddings: true
```

写入向量和生成查询向量时都会检查维度。当前数据库列是 `vector(768)`；更换为其他维度的模型时，需要同步修改数据库列定义并重建对应索引。

## 数据库连接

本机通过 SSH tunnel 使用服务器 PostgreSQL：

```text
Mac 股票 Agent
    ↓ 127.0.0.1:5433
SSH tunnel
    ↓ 服务器 127.0.0.1:5432
PostgreSQL + pgvector
```

在 `backend/.env` 中设置：

```dotenv
STOCK_AGENT_DATABASE_URL=postgresql+psycopg://用户名:密码@127.0.0.1:5433/stock_agent
```

不要提交包含真实密码的 `.env`。服务器数据库需要预先启用 pgvector：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## 已有数据库升级

在加入 embedding revision 和 dimension 之前创建的数据库，保持 SSH tunnel 运行并加载 `backend/.env` 后执行一次：

```bash
set -a
source backend/.env
set +a
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/migrate_day16_embedding_metadata.py
```

脚本会补充两列、从现有向量写入维度，并把旧 `index_config_id` 更新为包含 revision 和 dimension 的新 ID，从而保留已有向量。该脚本仅用于升级当前 Day16 schema；新数据库不需要运行。

## 验证方式

先保持 SSH tunnel 运行，然后在项目根目录加载环境变量：

```bash
set -a
source backend/.env
set +a
```

验证数据库和 pgvector：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_data_base.py
```

首次构建并检索：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_persistent_retrieval.py --mode build
```

再次运行时验证持久化复用；该模式会禁止调用 `build_company_index()`：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_persistent_retrieval.py --mode reuse
```

运行全部后端测试：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python -m pytest \
  backend/tests -q
```

## 完成标准

- SEC document、block、chunk 和 embedding 能写入 PostgreSQL。
- 重复写入返回 0 或 `False`，不会产生重复记录。
- 数据库读回的 block/chunk offset 仍能定位到 canonical document content。
- embedding model、revision 和 dimension 被记录并参与索引身份计算。
- 查询只搜索 `company_indexes.document_versions` 指定的文档版本。
- 进程重启后，`--mode reuse` 不重建索引也能返回结果和原始 SEC 来源。

Day17 再处理 filing freshness 和增量更新；Day16 只负责完整索引的持久化与复用。



                SEC HTML
                    │
                    ↓
            filing_documents
             整篇 canonical text
              /             \
             /               \
            ↓                 ↓
   filing_blocks        document_chunks
   原文结构定位           RAG 检索单元
      │                      │
      │ source_block_ids     │
      └────────────←─────────┘
                             │
                             ↓
                         embedding
                             │
                             ↓
                      similarity search
                             │
                             ↓
                          Evidence





company_indexes
      │
      │ 描述“这一整套索引已完成”
      │
      ↓

filing_documents
      │
      ├────────→ filing_blocks
      │
      └────────→ document_chunks
                       │
                       ↓
                chunk_embeddings
