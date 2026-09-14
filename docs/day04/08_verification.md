# 8. 统一错误模型与验收

先实现 `backend/src/stock_agent/schemas/errors.py`，再修改
`backend/examples/structured_agent.py`。离线验收脚本由我实现。
`PublicError`、`run_finished` 和下面的错误码都是本项目自定义的，
不是模型或 SDK 要求的字段。

## 按顺序完成的 TODO

- [x] **TODO 8.1，定义错误对象**：`errors.py` 已定义 `ErrorCode` 和 `PublicError`。`PublicError` 只包含 `code`（固定错误码）、`message`（固定安全提示）、`stage`（`model/tool/validation/task`），禁止额外字段或与错误码不一致的提示。入参是这三个固定字段；出参是可安全 `model_dump()` 的对象。
- [x] **TODO 8.2，生成安全错误**：`make_public_error(code: ErrorCode) -> PublicError` 接收一个固定错误码，按码查固定 `message` 和 `stage`，返回 `PublicError`；未知码会被拒绝，不输出原始异常文本。
- [x] **TODO 8.3，记录模型流程终态**：`model_loop(client, model, api_key, max_round, max_tool, events, model_timeout) -> int` 入参和退出码不变。各返回分支向 `events` 写入一次 `run_finished`；正常答案使用 `ResearchOutput.status`，失败时写固定公开错误，保留模型轮数和格式修复预算。
- [x] **TODO 8.4，记录入口异常**：`main(argv=None, *, events=None) -> int` 将总超时、HTTP/模型错误和主动取消写入安全终态；若 `model_loop` 已记录终态，则更新同一条。正常返回退出码；取消在客户端关闭后继续抛出 `CancelledError`。
- [x] **TODO 8.5，离线验收**：`verify_structured_agent.py` 的 `main() -> int` 无入参，复用已有离线 pytest，逐项打印通过/失败；全部通过返回 `0`，否则返回 `1`。不读取真实密钥或访问网络。
- [x] **TODO 8.6，记录边界**：已更新 `docs/day04.md`，将离线结果、既有最小真实响应和未验证的完整真实流程分开记录；缺少的耗时和用量不补造。已人工检查一条离线构造的“ID 合法但内容无支持”反例。

## 错误模型

建议的 `code` 对应关系：

| 情况 | code | stage |
| --- | --- | --- |
| JSON 语法无效 | `invalid_json` | `validation` |
| JSON 合法但不符合 `ResearchOutput` | `invalid_output` | `validation` |
| 引用了本次没有提供的证据 ID | `invalid_evidence` | `validation` |
| 把 fixture 标为 live 等模式不符 | `data_mode_mismatch` | `validation` |
| 模型没有 choices、正文为空或输出截断 | `incomplete_response` | `model` |
| 模型拒答 | `model_refusal` | `model` |
| 工具调用 ID 等协议错误 | `invalid_tool_call` | `tool` |
| 单轮模型请求超时 | `model_timeout` | `model` |
| 模型连接、HTTP 或其他调用失败 | `model_error` | `model` |
| 工具局部超时 | `tool_timeout` | `tool` |
| 整次任务总时限到期 | `total_timeout` | `task` |
| 主动取消 | `cancelled` | `task` |
| 模型轮数或工具执行预算耗尽 | `budget_exhausted` | `task` |

工具局部超时已有 `tool_failed` 事件，可由模型继续处理；不要把它
误记为整次任务的 `total_timeout`。`run_finished` 是终态事件，
每次运行最多一条；已有工具事件和 token 用量事件不是终态。
错误消息只从固定映射生成，不携带原始异常、密钥、请求头或内部推理。
`CancelledError` 在内部继续传播，不能因统一错误模型而被吞掉。

`run_finished` 的最小格式由本项目定义：成功时
`{"type":"run_finished","status":"completed"}` 或
`status="insufficient_information"`；失败时
`{"type":"run_finished","status":"failed","error": PublicError.model_dump()}`；
主动取消时 `status="cancelled"` 且 `error.code="cancelled"`。
每条 `run_finished` 还带有本次运行的 `run_id`，便于与工具和用量事件对应。
现有 `EvidenceValidationError.code="unknown_evidence_id"` 映射成公开的
`invalid_evidence`；`data_mode_mismatch` 保持同名。Pydantic 的
`json_invalid` 映射成 `invalid_json`，其余结构校验错误映射成
`invalid_output`。这些映射都不能直接复制异常文本。

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

## 2026-09-14 验收记录与局限

- **离线验收**：执行 `PYTHONPATH=backend/src python backend/examples/verify_structured_agent.py`，选定的 56 个 pytest 案例全部通过，退出码为 0。脚本只复用固定响应、假客户端和本地工具；运行结果不是来自真实模型。
- **当前完整 Agent 的真实调用**：目标模型 `glm-4.7-flash`；当前异步 HTTP 客户端依赖 `httpx==0.28.1`，结构化输出请求使用 `response_format={"type":"json_object"}`，提示词给出 `ResearchOutput` 的 JSON Schema。工具资料来自本地教学 fixture：模拟报价和公司介绍均标记为 `fixture`，报价预设时间为 `2026-09-11T09:00:00+08:00`。完整“工具请求 → 工具结果 → 结构化回答”流程**尚未真实验证**，因此这条流程没有可报告的真实耗时、token 用量或最终结果。
- **既有真实请求单独记录**：`docs/day04/02_structured_output.md` 已记录 `zai-sdk==0.2.3` 的一次最小 `json_object` 请求：返回 `insufficient_information`，用量为输入 424、输出 58、合计 482 token；该次没有工具调用，耗时当时未记录。后续两次工具与 JSON 模式同轮尝试均在首轮遭遇 HTTP 429，未得到 `choices` 或用量，不能据此判断组合能力。按此前约定，本轮不重试真实请求。
- **人工语义检查（离线构造，不是模型输出）**：本地报价工具的 `E1` 只给出虚构的 NVDA 报价 100 USD。构造 `facts=[{"text":"NVDA 下一季度营收一定翻倍","evidence_ids":["E1"]}]`，并设置 `data_mode="fixture"` 时，`ResearchOutput` 和 `validate_evidence(..., {"E1"}, "fixture")` 均通过；但 `E1` 根本没有营收资料，人工判断该句无证据支持。这表明当前代码只检查结果结构、证据 ID 归属和资料模式，**不能自动证明句子内容受到证据支持**。真实模型结果的同类人工检查仍待完整流程可调用后进行。
