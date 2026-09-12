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
