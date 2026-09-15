# 2. 评估运行器

位置：`evals/run_basic_cases.py`。运行器读取 JSONL、拒绝重复 ID 和错误行，复用 D04 的 `model_loop()` 与工具注册表，不另写一套 Agent。每项有独立 `run_id`、消息副本、证据 ID、预算和计时。离线模式用 `ScriptedClient` 返回固定模型消息；未知工具和非法参数通过原有白名单和 Pydantic 校验；超时案例使用可取消的慢 handler 替身。

```bash
PYTHONPATH=backend/src backend/.venv/bin/python evals/run_basic_cases.py --mode offline
PYTHONPATH=backend/src backend/.venv/bin/python evals/run_basic_cases.py --mode offline --case D05-07
# 真实模式只运行 real_api_allowed 案例；TODO D05-Core-1 完成后使用：
PYTHONPATH=backend/src backend/.venv/bin/python evals/run_basic_cases.py --mode real --case D05-02
```

结果写入 `evals/results/` 中的新 JSONL 文件，不覆盖旧结果。每项保存 `run_id`、输入快照、消息、工具事件、最终结构化回答、终态、安全错误、版本、预算、耗时、用量、自动判定和人工 `pending`。没有模型用量时写 `null`，不写 0。普通案例失败后继续；整体取消继续传播。真实模式显式选择，且只接收 `real_api_allowed` 的案例；缺密钥或模型时记为 `blocked`，不访问网络。不要在结果里记录密钥、请求头、原始异常或模型内部推理。

自动检查有失败或 `blocked` 时退出码非 0；全部自动通过时退出码 0，但人工 `pending` 不代表整体验收通过。
