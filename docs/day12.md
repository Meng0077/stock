# D12：RAG Tool 接入 Agent

2026-09-17：本地 fixture 范围内的 Day12 接入与验收已完成。尚未实现 SEC Provider、按需持久化索引或增量更新，这些继续按 Day13–17 推进。

## 当前调用流程

```text
ResearchRequest
    → LangChain Agent
    → retrieve_knowledge(company_id, question)
    → KnowledgeToolParams
    → execute_tool / TOOL_REGISTRY
    → 本地资料加载、分段、Embedding、向量检索
    → ToolMessage：JSON 证据列表
    → ResearchOutput
    → 本次 evidence_id 与 data_mode 校验
    → 运行结果和事件
```

业务实现仍位于 `backend/src/stock_agent/retrieval/knowledge.py`。LangChain adapter 只负责调用统一注册表并序列化结果，不另写一套检索逻辑。注册表用参数模型的字段调用 handler，支持公司代码和检索问题两个参数；原有报价、公司资料工具继续复用同一入口。

KnowledgeToolParams 复用现有公司参数约束，增加非空 question。工具名称不包含特定公司；当前资料目录为 `backend/fixtures/data/`，只具备本地已有资料的查询能力，不代表真实任意 ticker 查询已完成。

## 证据与无资料行为

- 报价及公司资料的证据 ID 为 `E-…`，RAG 片段为 `rag:{company_id}:{文件名}:{片段序号}`。
- 只从成功的 get_quote、get_company_profile、retrieve_knowledge ToolMessage 收集证据 ID。
- ResearchOutput 只是结构化回答提交工具，不是新的证据来源；失败工具也不提供证据。
- 最终 facts / inferences 中的所有引用必须属于本次实际提供的证据；请求模式限制本轮成功工具证据，最终模式由实际引用反推。
- 找不到对应本地文件时返回空列表，不加载 Embedding 模型。Agent 据此返回 insufficient_information，并说明缺少公司资料。

本次恢复了被注释的证据工具白名单，避免将结构化回答中的 ID 纳入允许引用的来源。无资料判断只处理文件不存在的业务情况，其他读取或程序异常继续传播，不增加通用异常兜底。

## 验证结果

自动测试：256 项通过。新增验证覆盖注册表传递两个已校验参数、adapter 委托统一入口，以及正常 RAG / 无本地资料两条完整 Agent 路径。完整路径测试使用本地临时文档和假 Embedding / 模型，不访问外部服务。

真实 DeepSeek 验证：使用现有配置及本地缓存的 all-mpnet-base-v2 模型运行 `evals/verify_rag_agent.py`，四个案例全部通过，脚本退出码为 0。

| 案例 | 预期 | 实际 |
| --- | --- | --- |
| quote_only | 调用 get_quote，completed，引用 E- 证据 | PASS |
| knowledge_only | 调用 retrieve_knowledge，completed，引用 rag: 证据 | PASS |
| quote_and_knowledge | 调用两类工具，completed，同时引用两类证据 | PASS |
| missing_documents | 查询无本地资料的 TSLA，调用检索工具，insufficient_information | PASS |

之前 quote_only / quote_and_knowledge 的 get_quote: 前缀与工具实际生成的 E- 不一致，已修正。评估脚本现在按各案例的 expected_status 判定，资料不足属于预期结果，不再统一要求 completed。

## 运行方式

在项目根目录执行自动测试：

```bash
backend/.venv/bin/python -m pytest -c backend/pyproject.toml
```

真实验证需要 `backend/.env` 配置 DeepSeek 模型及密钥，会产生模型调用：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python evals/verify_rag_agent.py
```

本次已缓存 Embedding 模型，也验证了以下命令；OFFLINE 只限制 Hugging Face 模型下载，DeepSeek 仍需联网：

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONPATH=backend/src backend/.venv/bin/python evals/verify_rag_agent.py
```

## 保留的后续工作

Day13 开始根据任意 ticker 发现真实 filing，Day14 补齐来源元数据和解析，Day15–17 处理按需索引、持久化复用和更新。当前每次本地检索仍会建立内存向量库，没有提前加入缓存。

四个案例是本次功能验收，不代表完整 RAG 质量评估。引用 ID 合法不等于句子被原文充分支持；Day11 的中文检索失败，以及模型扩展“需求增长”“训练与推理”等原文未明确给出的内容，仍需在后续固定评估中检查。
