# 3. 校验证据归属

实现位置：backend/src/stock_agent/agents/evidence_validation.py。

## 你来完成

当前 `validate_evidence(output, allowed_ids, evidence_modes, request_mode)` 的职责是：

1. allowed_ids 由程序根据本次实际提供的资料建立，不能从模型回答中反向收集。
2. 遍历 facts 和 inferences 的 evidence_ids，任何 ID 不在 allowed_ids 中都应失败。
3. 单条证据模式只能是 fixture / historical / live；同一 evidence ID 不能对应不同模式。
4. 请求模式限制本轮可用的数据环境；mixed 允许组合，其他模式只允许同类成功工具证据。
5. 根据最终实际引用的证据反推 output.data_mode；引用多种模式时为 mixed，没有引用时为 null。
6. 缺资料时允许 insufficient_information，不能为了让 schema 通过而编造事实或引用。
7. 返回经过检查的结果或抛出明确的业务错误；不把证据错误混成 JSON 解析错误。

## 案例

- 本次只提供 E1、E2，引用 E1 -> 通过。
- 引用 E99 -> 拒绝。
- E3 存在于资料库但本次没有提供 -> 拒绝。
- 没有证据、无事实、明确缺失信息且 data_mode=null -> 允许 insufficient_information。
- 本地 fixture 结果被模型标为 live -> 拒绝。
- fixture 请求中成功工具返回 historical 证据 -> 拒绝，即使最终没有引用。

合法 ID 仍可能支持不了句子，比如引用营收数据却声称超出市场预期。
这个函数只验证证据归属与模式，不声称已自动验证事实支持；人工检查应单独记录。
