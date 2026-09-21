# Day17：索引快照与增量更新

## 完成状态

2026-09-21：Day17 核心范围已完成。

当前实现能够：

- 精确复用相同 `company_id + as_of + index_config_id` 的快照。
- 从严格早于本次 `as_of` 的最近兼容快照继续更新。
- 通过 SEC accession number 找出新增 filing。
- 只下载、解析、切分和 embedding 新增 filing。
- 没有新增 filing 时复用原有文档版本和 chunk，只写入新的快照。
- 将修订 filing 作为新的 accession 保存，不覆盖旧版本和历史证据。
- 在索引阶段和检索阶段同时遵守 `as_of`，避免未来资料进入历史查询。
- 在新增文档或 embedding 失败时不写入新的 `company_indexes` 完成标记。

## 最终控制流

`ensure_company_index()` 按以下顺序处理：

```text
查询 exact snapshot
        │
        ├── 存在 → 直接返回，不查询 SEC
        │
        └── 不存在
              ↓
查询 latest compatible snapshot
        │
        ├── 不存在 → full build → 保存 snapshot
        │
        └── 存在
              ↓
        查询截至 as_of 可用的 SEC metadata
              ↓
        按 accession number 与历史 snapshot 做 diff
              │
              ├── 有新增
              │     ↓
              │  只处理新增 document / block / chunk
              │     ↓
              │  只生成新增 chunk embeddings
              │     ↓
              │  合并 document_versions
              │     ↓
              │  保存新 snapshot
              │
              └── 无新增
                    ↓
                 复用 document_versions 和 chunk_count
                    ↓
                 只保存新 snapshot
```

完成标记 `company_indexes` 始终在文档、block、chunk 和 embedding 成功写入后保存。前面的写入使用稳定 ID，可以在失败后重试；没有新快照就不会把部分导入声明为已完成索引。

## 快照语义

`company_indexes` 中的一条记录描述某个时间边界下可检索的完整文档集合：

| 字段 | 含义 |
| --- | --- |
| `company_id` | 规范化后的 ticker |
| `as_of` | 本次研究允许使用资料的时间上界 |
| `index_config_id` | parser、chunk 和 embedding 配置的组合身份 |
| `document_versions` | `document_id → content_hash` 的不可变版本集合 |
| `chunk_count` | 该快照包含的 chunk 总数 |

两种查询的边界不同：

```text
exact snapshot
company_id 相同
AND as_of == request.as_of
AND index_config_id 相同

latest compatible snapshot
company_id 相同
AND snapshot.as_of < request.as_of
AND index_config_id 相同
ORDER BY snapshot.as_of DESC
LIMIT 1
```

配置发生变化时 `index_config_id` 也会变化，因此旧 parser、切分规则或 embedding 生成的索引不会进入增量复用。

## 增量更新规则

系统先根据 base snapshot 的 `document_versions` 查询已保存文档，从中收集 accession number，再与 SEC metadata 比较：

```text
available SEC accessions - indexed accessions = new filings
```

每个新增 filing 执行：

```text
load_relevant_filing_documents()
        ↓
save_filing_document()
        ↓
save_filing_blocks()
        ↓
split_filing_document()
        ↓
save_document_chunks()
        ↓
embed_new_chunks()
        ↓
save_chunk_embeddings()
```

旧 accession 不会再次进入这条处理链。`10-K/A`、`10-Q/A`、`20-F/A` 等修订拥有独立 accession，因此会新增文档版本；旧 snapshot 继续引用旧版本，新 snapshot 保存旧、新版本合集。

## 历史查询安全

防止 future-data leakage 依靠两层约束：

1. **索引选择**：`get_latest_compatible_company_index()` 只选择 `snapshot.as_of < request.as_of` 的快照；SEC Provider 只返回 `accepted_at <= as_of` 的 filing。
2. **向量检索**：`search_similar_chunks()` 使用 snapshot 的 `document_versions` 过滤候选 chunk，数据库里即使存在未来 filing 的向量，也不能进入本次历史结果。

允许从过去快照增量更新到未来时间；禁止未来快照服务更早的请求。

## 验收

单元测试覆盖：

- exact snapshot 命中后不进入 freshness 流程。
- 没有 compatible snapshot 时执行 full build。
- 没有新增 filing 时只写新 snapshot。
- 有新增 filing 时合并文档版本并增加 chunk count。
- `process_new_filings()` 将 config 传给 chunk 持久化。
- exact 查询使用 `as_of == request.as_of`。
- compatible 查询使用 `as_of < request.as_of`。
- pgvector 查询只搜索 manifest 指定的 document versions。

最终验收脚本：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python \
  evals/verify_incremental_index.py
```

预期输出：

```text
PASS full build
PASS incremental update processes only new filing/chunks
PASS exact snapshot reuse
PASS historical retrieval excludes future documents
PASS Day17
```

完整回归：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python -m pytest \
  backend/tests -q
```

当前结果为 `305 passed`。最终验收使用固定 filing 和模拟外部边界，能够稳定验证控制流与不变量，不依赖服务器数据库状态或当天 SEC 数据变化。

## 当前边界

- SEC Provider 当前读取 submissions 的 recent filing 列表，并在一次 freshness 检查中使用最近 10 份受支持 filing；更早的历史清单读取仍是 Day13 遗留项。
- 快照保存研究时间边界 `as_of`，尚未单独保存实际执行 freshness 检查的 wall-clock `checked_at`。
- 自动验收使用模拟 SEC、数据库和 embedding 边界；真实 PostgreSQL/pgvector 的持久化连接与复用由 Day16 验收脚本覆盖。
- 并发请求对同一新快照可能重复执行下载和 embedding；数据库唯一键可以避免重复记录，但当前没有跨进程构建锁。

这些边界不影响 Day17 的单进程面试版核心验收，但不能据此声称已经覆盖完整 SEC 历史、并发生产部署或 freshness 监控。
