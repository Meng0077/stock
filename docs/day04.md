# D04：结构化输出、超时与取消

这里是练习任务，不代表功能已实现。D03 的工具往返与预算检查已有验收记录；继续按下面顺序完成 D04。
D04 验证的是研究结果的结构、证据归属和异步调用边界。新版计划中的行情、RAG、确定性决策和用户仓位风险分别在后续开发日实现，不要求今天做进 ResearchOutput。
先离线验证，再按任务说明单独验证真实模型；不预装新依赖，模型结构化输出能力和异步客户端接口在实现时核对官方文档及锁定版本。

## 分步任务

1. [定义研究结果](day04/01_output_schema.md)
2. [请求与解析结构化输出](day04/02_structured_output.md)
3. [校验证据归属](day04/03_evidence_validation.md)
4. [限制格式修复](day04/04_repair.md)
5. [超时与预算](day04/05_timeouts.md)
6. [异步客户端生命周期](day04/06_async_client.md)
7. [取消与清理](day04/07_cancellation.md)
8. [统一错误与验收](day04/08_verification.md)

## 实现位置

- backend/src/stock_agent/schemas/research_output.py：研究结果模型。
- backend/src/stock_agent/schemas/errors.py：统一错误模型。
- backend/src/stock_agent/agents/evidence_validation.py：证据 ID 业务校验。
- backend/examples/structured_agent.py：逐步整合结果生成、一次格式修复及异步资源管理。
- backend/examples/timeout_cancel.py：离线超时与取消练习。
- backend/examples/verify_structured_agent.py：离线验收。

从项目根目录、已激活的虚拟环境运行，统一使用：

```bash
PYTHONPATH=backend/src python backend/examples/timeout_cancel.py
PYTHONPATH=backend/src python backend/examples/verify_structured_agent.py
PYTHONPATH=backend/src python backend/examples/structured_agent.py --preview
```

部分输出模型代码正在编写，其余示例仍有占位 TODO；以实际运行结果和下方完成清单判断进度，命令无输出不等于通过验收。
实现时保留 D03 示例；工具声明、调用 ID 校验及执行回传复用 `stock_agent.agents.tool_calling`，工具业务入口仍复用注册表。

## 完成清单

- [ ] 输出模型通过正常与错误输入检查。
- [ ] 实际所选模型的结构化输出方式已核对并记录。
- [ ] 伪造引用被拒绝，信息不足可明确结束。
- [ ] 格式修复最多一次，并计入预算与总时限。
- [ ] 工具超时和任务总超时分别验证。
- [ ] 客户端复用且正常关闭。
- [ ] 取消被传播、资源被清理、取消后无新请求。
- [ ] 离线案例有结果，真实模型案例单独标记。
- [ ] 能解释类型正确、证据归属正确和事实有支持之间的区别。
