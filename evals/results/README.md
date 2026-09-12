# 评估结果

目前没有结果。实现运行器后用唯一文件名保存 JSONL，不覆盖旧运行。
每项保存 run_id、case_id、dataset_version、execution_mode、started_at、input_snapshot、代码/模型/SDK/提示词版本、参数、事件、终态、final_output、safe_error、调用次数、耗时、usage、automatic_verdict、human_review。
人工 verdict 使用 pending/pass/fail。未知用量为 null。离线结果明确标注 offline。
不保存密钥、请求头和模型内部推理。共享结果前检查敏感信息。
