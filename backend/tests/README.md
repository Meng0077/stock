# pytest 测试入口

在项目根目录、已激活的虚拟环境执行：

```bash
python -m pytest -c backend/pyproject.toml
python -m pytest -c backend/pyproject.toml backend/tests/test_tool_params.py -v
```

也可以进入 backend 后执行 `python -m pytest`。
配置已指定 src 的导入路径，不需要额外设置 PYTHONPATH。

新环境安装开发依赖：

```bash
python -m pip install -r backend/requirements-dev.lock.txt
```

pyproject.toml 的 dev 可选依赖声明测试工具；requirements-dev.lock.txt 记录开发依赖版本，复用运行依赖快照。

- test_tool_params.py：原手工参数案例、长度边界及赋值校验。
- test_tools.py：模拟数据标记、未知公司、返回副本等业务行为。
- assert 判断结果；pytest.raises 判断预期异常；parametrize 让每行数据单独运行。
- 不需要手写 passed 或 main。pytest 自动汇总并在失败时返回非零退出码。

这些是离线测试，不读取 .env、不调用模型。D03/D04 未实现的内容不标为通过；完成后你继续添加相应测试。
examples 中的教学演示保留，但自动验收逐步放到 tests 中。
