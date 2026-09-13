# 2. 请求与解析结构化输出

实现位置：backend/examples/structured_agent.py。

## 你来完成

1. 先用本地合法和非法 JSON 字符串调用 ResearchOutput.model_validate_json，熟悉解析错误。
2. 查智谱官方文档及已安装 SDK，记录 GLM-4.7-Flash 支持的输出模式。
3. 若支持 JSON Schema 约束，使用 ResearchOutput.model_json_schema()；若只支持 JSON 模式，使用该模式并在提示中说明字段。
4. 不凭别家 SDK 示例猜参数；不把 JSON 模式描述成一定符合业务 schema。
5. 模型没有合适的原生模式时，明确记录限制，不静默更换模型或启用付费模型。
6. 保留 --preview：展示输入和 schema，不调用 API、不输出密钥。
7. 无 choices、空正文、拒答或长度截断应识别为失败，不接受部分结果为完整分析。
8. 完整响应先做应用层 Pydantic 校验，再做证据和 data_mode 校验。

## 验收

- 合法 JSON 但缺字段仍会失败。
- ```json 代码围栏不是直接可解析的 JSON；按失败路径处理，不使用危险执行或随意修补字符串。
- 结构化生成与工具调用若不能在同一请求组合，可在工具结束后单独请求最终结果；这一请求也计入模型预算。
- 保存使用的模型、SDK 版本、输出方式及官方文档链接，真实结果与离线输入分开标记。

## TODO 2 查证记录（2026-09-13）

- 项目配置的模型名是 `glm-4.7-flash`；[官方模型页](https://docs.bigmodel.cn/cn/guide/models/free/glm-4.7-flash) 使用这个调用名，并列出“结构化输出：支持 JSON 等结构化格式输出”。
- 本地虚拟环境安装的是 `zai-sdk==0.2.3`（项目在 `backend/pyproject.toml` 中也锁定该版本）。已安装 SDK 的 `client.chat.completions.create()` 接收 `response_format` 参数，并将其放入聊天请求体；该参数在 SDK 中标为通用 `object`，**不能仅凭 SDK 类型推断服务端接受 JSON Schema 约束**。
- [官方结构化输出指南](https://docs.bigmodel.cn/cn/guide/capabilities/struct-output) 给出的参数是 `response_format={"type": "json_object"}`，并要求在 `messages` 中说明期望字段。[聊天补全 API 文档](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8) 列出 `text`、`json_object`，未提供 `json_schema` 请求格式。
- 因此 TODO 3 按**官方已文档化的 JSON 模式**实现：`response_format={"type": "json_object"}`，提示词说明 `ResearchOutput` 的字段与规则，完整正文仍交给 `ResearchOutput.model_validate_json()` 做应用层校验。`model_json_schema()` 可以辅助编写提示词或预览，但不能当作已获得服务端严格 schema 约束。
- 上述输出方式先经文档与本地 SDK 静态核对；下方另记一次最小真实请求。完整 D04 工具往返和结构化结果组合仍留待 TODO 7 验收。

## 最小真实响应示例（2026-09-13）

这次直接请求 `glm-4.7-flash`，使用 `response_format={"type": "json_object"}`、关闭思考，并明确告知没有提供 NVDA 报价或公司资料。它只验证 JSON 模式与本地 `ResearchOutput` 解析；**没有执行工具，也不是完整 D04 流程验收**。

```text
response 类型: Completion
response.model: glm-4.7-flash
len(response.choices): 1
response.choices[0].finish_reason: stop
response.choices[0].message.content:
{"status":"insufficient_information","data_mode":"fixture","missing_information":["NVDA 报价","NVDA 公司资料"],"facts":[],"inferences":[]}
ResearchOutput.model_validate_json(content): 通过，status=insufficient_information
usage: prompt_tokens=424, completion_tokens=58, total_tokens=482
```

`response` 是 SDK 的完成对象；应在检查 `choices`、结束原因和正文后，将 `message.content` 字符串交给 Pydantic。`data_mode` 是本次提示给模型的模式，完整流程仍需由程序与实际资料核对。

## Task 2 后续验证（2026-09-13）

- 离线响应边界已补齐：无 `choices`、空正文、截断，以及显式拒答标记或常见纯文本拒答，均直接失败且不进入格式修复。截断的工具调用也不会执行。当前锁定的 `zai-sdk==0.2.3` 消息类型没有独立的 `refusal` 字段，因此纯文本拒答采用常见开头识别，不能保证覆盖所有自然语言表达。
- 用已配置的 `glm-4.7-flash` 和 `zai-sdk==0.2.3` 两次尝试 `tools` 与 `response_format={"type":"json_object"}` 同轮请求；两次均在首轮返回 `APIReachLimitError`（HTTP 429），没有拿到 `choices`，也没有执行工具。**这不能证明两种参数可组合，也不能证明不可组合。**
- 因限额阻断，完整的“模型请求工具 → 本地 fixture 工具结果 → 结构化最终回答”尚未完成真实验收；Task 2.2、2.3 保留待验证。离线假客户端测试不替代真实服务结果。
