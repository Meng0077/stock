# D09：LangChain 结构化输出与安全边界收口

- 整理与验证日期：2026-09-16。
- 状态：核心整合和截断保护已完成；无 choices、非法 JSON 的 LangChain 路径专项验收按用户要求遗留，不标记全部验收完成。
- 参考：[Week 2 计划](week2.md)、[总开发计划](../stock-agent-python-development-plan.md)、[D08 对照报告](day08/report.md)。

## 当前实现

`build_langchain_agent` 注册固定的两个只读工具，以及工具错误、模型预算、工具预算和截断响应 middleware。结构化验证脚本显式使用 `ToolStrategy(ResearchOutput)`。

`run_research` 的控制流是：

```text
ResearchRequest → Agent 流式运行 → 收集已发生的工具事件
  → runtime 错误映射，或 ResearchOutput + 证据校验
  → run_finished → 统一返回
```

返回字段固定为 `run_id`、`status`、`output`、`error`、`events`。成功或信息不足时保留 `ResearchOutput`；失败时 `output=None`，错误只包含现有 `PublicError` 的固定错误码、阶段和安全提示，不返回原始异常。

## 已验证的边界

| 项目 | 实现与结果 |
| --- | --- |
| 结构化输出 | 合法结果可收口；不合法的结构化工具参数在关闭框架修复时返回 `invalid_output` |
| 证据归属 | 只接受本次成功白名单工具结果中的 ID；虚构引用返回 `invalid_evidence` |
| 资料模式 | 与请求的 `data_mode` 核对，不匹配返回 `data_mode_mismatch` |
| 模型预算 | 最多 3 轮；实际 Agent 重复请求工具后返回 `budget_exhausted` |
| 工具预算 | 最多 4 次；超预算批次停止，不继续执行；返回 `budget_exhausted` |
| 超时 | 单工具超时返回错误 ToolMessage；模型请求超时映射为 `model_timeout`；任务总时限为 20 秒，到期取消流并返回 `total_timeout` |
| 取消 | 现有工具循环取消测试验证 `CancelledError` 向上传播，不变成工具业务错误 |
| 截断响应 | `finish_reason="length"` 返回 `failed / incomplete_response`，不接受部分结果、不执行截断工具调用、不再请求模型修复 |
| 运行事件 | 记录开始、工具请求与结果、最终终态；失败仍保留此前已发生的工具事件，均使用同一 `run_id` |

截断检查位于模型节点提交结果前的 `wrap_model_call` middleware。框架可能先解析结构化结果或构造格式错误消息，但截断响应不会提交为成功 state，也不会进入下一轮模型修复；若结构化校验先抛出异常，则根据该异常携带的原始模型消息优先映射为 `incomplete_response`。

## 本次修复与执行记录

- 修复事件收集函数缺失导入、`except` 后误用已清除的异常变量、错误映射引用不存在的异常类。
- 证据校验补齐请求的资料模式；预算错误复用现有 `budget_exhausted`。
- 统一所有成功与失败返回结构，保留运行身份、事件和安全错误。
- 增加截断文本、工具请求、合法结构化结果、不合法结构化结果（开启／关闭框架修复）的离线案例，验证不会执行工具或继续调用模型。
- 增加先成功调用工具、再收到截断响应的案例，验证历史工具事件保留。
- 全量后端测试：**226 passed**，另有一条现有 Starlette / AnyIO 弃用警告。
- 本轮使用 scripted/fake model，未调用真实模型；不将这些测试表述为真实模型准确率。

执行命令（从仓库根目录）：

```bash
backend/.venv/bin/python -m pytest backend/tests -q
```

## 明确遗留与后续范围

- [ ] 无 choices 的 LangChain 路径专项验收。
- [ ] 非法 JSON 的 LangChain 路径专项验收。

以上两项按用户要求暂不处理；Manual Agent 原有案例不能替代 LangChain 路径验收。

FastAPI 主 runner 仍使用 Manual Agent，CLI / API 与前端联调属于 D10，不计入 D09 遗留项。
