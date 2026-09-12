# 3. pytest 自动检查

位置：backend/tests/test_evaluation_rules.py。

- 用 parametrize 检查结果结构、明确终态、fixture 标签及引用归属。
- 用 spy/计数器确认未知工具、非法参数的 handler 执行次数为 0。
- 验证工具调用 ID 对应和模型/工具预算，不只检查日志文案。
- 超时后确认符合预期的停止行为；避免精确毫秒断言。
- 给检查器一份合法结果与一份故意违规结果，确保确实会判失败。
- pytest 只离线，不读取真实密钥、不请求模型。
- 未实现不使用 assert True 或无条件 skip 冒充完成。

运行：python -m pytest -c backend/pyproject.toml
pytest 证明指定程序行为符合规则，不自动证明分析事实正确。
