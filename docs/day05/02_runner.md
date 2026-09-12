# 2. 实现评估运行器

位置：evals/run_basic_cases.py。复用现有 Agent，不复制一套业务循环。

1. 读取 JSONL，拒绝重复 ID，错误行显示行号。
2. 实现 --mode offline/real 与 --case；默认 offline，真实模式显式选择。
3. 每项独立 run_id、messages、预算与计时。
4. 离线注入 scripted_responses 与工具替身；未实现、未准备记为 blocked。
5. real 模式只运行 real_api_allowed 的案例，不用离线结果冒充真实响应。
6. 保存输入快照、事件、最终结果、终态、版本、耗时、用量和安全错误。
7. 结果写入 evals/results/ 的唯一 JSONL 文件，不覆盖旧结果。
8. 普通案例失败记录后继续；整体取消必须传播。
9. 汇总自动符合率，有失败或 blocked 则非零退出。人工 pending 不能称为整体验收通过。
10. 不记录密钥、Authorization、原始异常或模型内部推理；未知用量为 null，不能写成 0。

运行约定（待实现）：
```
PYTHONPATH=backend/src python evals/run_basic_cases.py --mode offline
PYTHONPATH=backend/src python evals/run_basic_cases.py --mode real --case D05-02
```
