# 3. pytest 自动检查

位置：`backend/tests/test_evaluation_rules.py`。测试直接运行 10 个固定响应，通过执行事件和 spy 确认：非法参数、未知工具进入 handler 的次数为 0；慢工具超时；工具调用 ID 请求与结果对应；引用只使用本次提供的证据；资料模式仍为 `fixture`；模型和工具预算有效；每项只有一个终态。

检查器还用故意篡改的证据 ID、`live` 标记、工具调用 ID、预算与公开错误验证会判失败。结果文件测试确认不会覆盖旧文件、未知 token 用量是 `null`。真实路径只用假客户端检查资源关闭，不发网络请求。

```bash
backend/.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests/test_evaluation_rules.py -v
```

2026-09-14：D05 测试 9 个通过，全量测试 91 个通过。pytest 证明程序在指定输入下符合规则，不能自动证明分析中的每句话都有事实支持。
