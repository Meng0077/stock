# 第 5 步：解析模型的工具调用请求

实现位置：backend/examples/manual_agent.py。

## 你来完成

1. 从 response.choices[0].message 中读取 tool_calls；先检查 choices 是否为空。
2. 没有工具调用时，检查是否存在正常结束的最终正文；空正文或截断不能当成成功。
3. 有工具调用时遍历列表，读取每次调用的 id、function.name、function.arguments。
4. function.arguments 通常是 JSON 字符串：使用 json.loads，不使用 eval。
5. JSON 解析成功后，确认结果是 dict；合法 JSON 也可能是数组、数字或 null。
6. 确认调用 ID 非空，同一条消息内 ID 不重复；否则停止本次流程并报告协议错误，不能猜 ID。
7. 将工具名和参数字典交给 execute_tool，由注册表入口检查白名单和 Pydantic 参数规则。

## 离线案例

- '{"company_id":"NVDA"}'：成功解析。
- '{"company_id":'：JSONDecodeError，不能执行工具。
- '[]'、'null'：JSON 合法但不是参数对象，不能执行工具。
- 空 company_id、额外字段：ValidationError，不能执行工具。
- 未知工具名：拒绝，不能查找或执行任意函数。
- 缺少或重复调用 ID：协议错误，不能继续发送不匹配的消息。

可提取 parse_arguments(raw: str) -> dict，便于独立验证。
先用手工构造的数据测试，不必让模型故意生成错误。
