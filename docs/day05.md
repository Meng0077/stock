# D05：第一周验收

今天验证 D01–D04，不增加新框架。先完成待验收功能；未实现记为 blocked，不能算通过。

1. [固定案例](day05/01_cases.md)：准备 10 个输入与预期。
2. [评估运行器](day05/02_runner.md)：保存输入、事件、结果及版本。
3. [pytest 检查](day05/03_checks.md)：验证确定性的结构与权限规则。
4. [人工复核](day05/04_review.md)：检查事实支持并填写报告。
5. [演示讲解](day05/05_demo.md)：演示正常与失败路径。

代码入口：evals/run_basic_cases.py；案例：evals/basic_cases.jsonl；测试：backend/tests/test_evaluation_rules.py。
报告：docs/day05/report.md；演示：docs/day05/demo.md。
当前只有模板和 TODO，没有执行 D05 验收。

## 完成标准
- [ ] 10 个案例可复现，并进入明确终态。
- [ ] 非法工具无法执行，非法参数不能传给 handler。
- [ ] fixture 不被当成实时数据。
- [ ] 保存输入、工具事件、最终结果、版本和人工判定。
- [ ] 自动检查与人工事实复核分开报告。
- [ ] 完成真实工具往返与离线故障演示。
- [ ] 用自己的话解释白名单与预算的必要性。
