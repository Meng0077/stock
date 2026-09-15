# D05：第一周验收

Day 5 验证 D01–D04 的 Agent，不增加新框架。10 个固定案例已接入现有 `structured_agent.model_loop()`，离线评估 10/10 自动通过；这只证明固定输入下的程序规则，不证明模型实际会这样回答。LangChain、RAG、行情、新闻和仓位风险留到后续开发日验收。

1. [固定案例](day05/01_cases.md)：10 个输入、固定模型响应、故障注入和预期，版本 `day05-v2`。
2. [评估运行器](day05/02_runner.md)：逐项运行并保存输入、消息、事件、结果、版本、耗时和用量。
3. [pytest 检查](day05/03_checks.md)：检查真实执行事件、handler 次数、证据 ID、资料模式和预算。
4. [人工复核](day05/04_review.md)：由你逐条判断事实有没有证据支持。
5. [演示讲解](day05/05_demo.md)：由你讲清一次正常路径和一次被拦截的错误路径。

运行：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python evals/run_basic_cases.py --mode offline
backend/.venv/bin/python -m pytest -c backend/pyproject.toml
```

实际离线结果和 run_id 见 [验收报告](day05/report.md)。演示提纲见 [demo.md](day05/demo.md)。

## 完成情况

- [x] 10 个案例可复现，且每项进入明确终态（离线）。
- [x] 未知工具和非法参数未进入 handler；慢工具按局部超时停止（离线）。
- [x] 工具和最终回答都保留 `fixture` 标记，证据 ID 仅允许本次输入或成功工具结果中的 ID。
- [x] 保存输入快照、消息、工具事件、终态、最终结果、版本、耗时、用量和人工 `pending`。
- [x] 自动符合率与人工事实复核分开；全量 pytest 91 个通过。
- [ ] 真实模型完成一次工具往返，记录结果；此前 HTTP 429，当前未重试。
- [ ] 人工复核每条事实，并由你完成 3～5 分钟演示讲解。

## 留给你的 3 个核心 TODO

- **TODO D05-Core-1：真实工具往返。** 输入：可用的 `ZHIPU_API_KEY`、`MODEL_NAME`，以及案例 `D05-02`。执行 `PYTHONPATH=backend/src backend/.venv/bin/python evals/run_basic_cases.py --mode real --case D05-02`。输出：一个独立的 real JSONL 结果文件；在报告里写明实际终态、工具调用、耗时和可获得的 token 用量。若仍是 429，记录失败，不算通过，也不要反复重试。
- **TODO D05-Core-2：人工证据复核。** 输入：报告中列出的离线结果文件的 `final_output`、`input_snapshot.evidence` 和 `tool_succeeded.fixture_result`。输出：在 `docs/day05/report.md` 为 10 个案例逐项填写 `pass/fail` 和一句证据理由；重点解释 E99 被拒绝与“合法 ID 但句子无支持”的区别。这里没有函数返回值，最终产物是可追溯的人工判定。
- **TODO D05-Core-3：面试演示讲解。** 输入：D05-02、D05-07 的结果和相应代码。输出：填好 `docs/day05/demo.md`，用自己的话讲清模型请求、白名单、参数校验、工具结果回传、预算和人工复核各起什么作用。
