# 第一周验收报告（离线自动检查已完成）

## 实验条件

- 日期：2026-09-14T10:28:30.956453+00:00（UTC）。
- 结果文件：[D05 离线结果](../../evals/results/d05-offline-20260914T102831-063eec2a.jsonl)；每行包含输入和固定响应快照、事件、最终结果、版本、预算与耗时。
- 代码版本：`a3126df-dirty`（dirty 表示运行时有未提交改动）；源代码 SHA-256：`288a2426f4d117b58a4f32f2da009881c673dc5440bc5b141855c1ea1e54d896`；数据集：`day05-v2`；提示词：`d04-structured-v1`。
- Python `3.11.1`，zai-sdk `0.2.3`，httpx `0.28.1`；模型为 `scripted`，未请求真实 API。
- 预算：模型最多 3 轮、工具执行最多 4 次、单请求输出上限 5000 token、任务总时限 120 秒。JSON 模式为 `json_object`。

## 案例结果

| 案例 | run_id | 预期/实际终态 | 自动 | 人工 | 模型请求 | 工具执行 | handler | 耗时 ms | token |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| D05-01 | `9577f556-581a-4a6d-8290-e0aed03de631` | `completed` / `completed` | pass | pending | 1 | 0 | 0 | 1.38 | null |
| D05-02 | `2967f001-a6cc-422c-bed3-9666735aa3a1` | `completed` / `completed` | pass | pending | 2 | 1 | 1 | 1.69 | null |
| D05-03 | `e833f573-74b6-4371-a47c-d8711629b04d` | `completed` / `completed` | pass | pending | 2 | 1 | 1 | 0.94 | null |
| D05-04 | `3d894e0c-d877-4b36-808c-2c03dc31f610` | `insufficient_information` / `insufficient_information` | pass | pending | 1 | 0 | 0 | 0.57 | null |
| D05-05 | `fcf8b056-13b6-46c2-b308-f2e2a1324051` | `insufficient_information` / `insufficient_information` | pass | pending | 1 | 0 | 0 | 0.58 | null |
| D05-06 | `2b3bed75-c4c1-4851-b751-4fb29b452d0a` | `insufficient_information` / `insufficient_information` | pass | pending | 2 | 0 | 0 | 0.96 | null |
| D05-07 | `a88b1713-2d78-4b05-b807-360d2f2226ec` | `insufficient_information` / `insufficient_information` | pass | pending | 2 | 0 | 0 | 0.85 | null |
| D05-08 | `a32f0ce0-fe0c-4e60-be1b-c79b55a5f178` | `insufficient_information` / `insufficient_information` | pass | pending | 2 | 1 | 1 | 7.46 | null |
| D05-09 | `55b7a726-ca0f-48b3-afed-ee3f557ee7fa` | `invalid_evidence` / `invalid_evidence` | pass | pending | 1 | 0 | 0 | 0.67 | null |
| D05-10 | `7fc803fd-c4d5-490e-82d5-b33378e66e1c` | `budget_exhausted` / `budget_exhausted` | pass | pending | 3 | 2 | 2 | 1.02 | null |

## 指标与判断

- 离线自动符合率：10/10；自动失败 0、blocked 0。全量 pytest：91 个通过，其中 D05 检查 9 个通过。
- 人工判定：10 项 pending，已判 pass 0、fail 0。真实请求成功数：0（本轮没有调用真实模型）。
- token 用量全部为 null，因为固定响应不提供模型用量；这不是 0 token。耗时是本机离线执行时间，不代表真实 API 延迟。
- D05-06、07 的 handler 次数为 0，说明错误参数和未知工具没有执行；D05-08 进入 handler 1 次后触发局部超时。D05-09、10 的自动通过表示预期错误被正确拦截，并非正常分析成功。

## TODO D05-Core-2：人工事实复核

请对每个案例填写 `pass/fail` 和一句具体理由。输入是结果文件中的 `final_output`、`input_snapshot.evidence`、`tool_succeeded.fixture_result`；输出是可追溯的人工结论。重点核对 D05-02 的 100 美元是否明确是教学模拟价、D05-05 是否承认数据冲突、D05-09 的 E99 为什么不能用。

| 案例 | 人工判定 | 证据理由 |                                                                                        |------------------------------------------------------------------------------------------------------------- |
| D05-01 | pass | 最终回答称“本季度营收为 100 万美元”，与 E1 的虚构教学资料完全一致；数字、单位、报告期均未混淆，并正确引用 E1。                                                |
| D05-02 | pass | 工具 E1 明确给出 NVDA 教学模拟报价 100.0 USD；最终回答写为“教学模拟报价为 100 美元”，未描述成实时行情，数字、币种和数据模式均与 fixture 一致。                     |
| D05-03 | pass | 工具 E1 说明 NVIDIA 提供 GPU 及相关计算平台；最终事实与该描述一致，并明确使用“教学资料显示”，没有把 fixture 扩张成未经支持的事实。                               |
| D05-04 | pass | 输入没有净利润证据，最终未编造任何利润事实，正确返回 `insufficient_information`，并明确指出缺少净利润数据。                                           |
| D05-05 | pass | E1 为 100 万美元、E2 为 120 万美元，属于同公司、同季度、同口径冲突；最终同时陈述两个数值并明确指出无法判断哪一个正确，没有自行选择其中一个。                                |
| D05-06 | pass | 工具参数为空，被判为 `invalid_arguments`，handler 未执行；最终没有编造报价，并明确说明因工具参数错误未取得报价。                                        |
| D05-07 | pass | 请求的 `delete_file` 不在工具白名单中，被判为 `unknown_tool`，handler 未执行；最终明确承认未取得报价，没有伪造工具成功结果。                             |
| D05-08 | pass | `get_quote` 实际进入 handler 后发生 `tool_timeout`；最终没有使用不存在的报价数据，并正确说明工具调用超时、未取得报价。                                 |
| D05-09 | pass | 固定响应试图用未提供的 E99 支持营收事实；允许证据实际只有 E1，因此该引用归属无效。系统正确以 `invalid_evidence` 阻止结果进入最终输出。本项 pass 表示错误被安全拦截，不表示分析正常完成。 |
| D05-10 | pass | 模型持续请求工具而未形成最终回答，达到模型轮数预算后以 `budget_exhausted` 终止；没有无限循环，也没有在预算耗尽后生成未经验证的最终结果。本项 pass 表示预算保护正确生效。             |


## 真实流程与限制

**TODO D05-Core-1：** 运行 D05-02 的真实模型工具往返，另存 real 结果并追加到这里。此前同轮工具与 JSON 模式请求遇到 HTTP 429，本轮按约定未重试；不能把离线 10/10 写成真实模型通过率。

D05-Core-1：PASS

2026-09-14 使用 DeepSeek `deepseek-v4-flash`
执行 D05-02 真实模型工具往返。

结果：
- execution_mode: real
- terminal_status: completed
- automatic_verdict: pass
- automatic_errors: []
- model requests: 2
- tool executions: 2
- total tokens: 2261
- elapsed: 2.756s
- response_format: json_object
- 完成真实 tool_call → fixture handler → tool result →
  最终结构化 ResearchOutput 往返

模型额外调用了 get_company_profile；
该调用合法且未影响本次验收，但属于可进一步优化的非必要工具调用。

自动检查验证结构、调用 ID、白名单、资料模式和引用归属；它不能证明“句子内容真的由所引用资料支持”。人工复核完成前，Day 5 的整体验收仍未完成。
