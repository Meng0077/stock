# 8. 统一错误模型与验收

实现位置：schemas/errors.py、examples/verify_structured_agent.py，并在 structured_agent.py 中使用。

## 错误模型

定义公开错误对象，包含稳定的 code 和安全的 message；可加 stage 表示 model/tool/validation。
建议区分：invalid_json、invalid_output、invalid_evidence、data_mode_mismatch、
model_error、tool_timeout、total_timeout、cancelled、budget_exhausted、incomplete_response。
选择明确可维护的类别即可，不必实现复杂异常继承体系。
只允许白名单字段进入日志，不携带原始异常、密钥、请求头或内部推理。
CancelledError 在内部继续传播，不能因统一错误模型而被吞掉。

## 离线验收

用固定响应或假客户端，验证：

1. 正常结构、合法证据 -> completed。
2. 缺字段、错误类型、非法 JSON -> 最多修复一次。
3. 结构合法但引用 E99 -> invalid_evidence，不执行格式修复。
4. 无证据且明确缺失信息 -> insufficient_information。
5. fixture 被标为 live -> data_mode_mismatch。
6. 局部慢工具 -> tool_timeout；流程总时限耗尽 -> total_timeout。
7. 主动取消 -> cancelled、清理完成、后续请求次数为 0。
8. 模型轮数或工具预算耗尽 -> 不继续调用；格式修复无法绕过预算。
9. 空响应/截断 -> incomplete_response，不当成完整结果。
10. 使用假敏感标记验证日志不会输出原始异常和凭据。

检查实际调用次数和终态，不只匹配打印文案。不同案例独立运行，不能共享剩余预算或旧任务状态。
全部结果与预期比较；有一项不符就以非零退出码结束。
时间检查预留调度误差，优先验证取消、清理和停止新调用，不使用精确到毫秒的断言。

## 真实调用与记录

单独记录模型、SDK/HTTP 客户端版本、结构化输出方式、资料版本、耗时、用量和结果。
本地模拟成功不代表真实模型接口验证成功。
人工检查至少一条“合法证据 ID，但句子超出证据”的结果，记录此检查仍有局限。
在 docs/day04.md 更新实际完成项，并说明未验证项。
