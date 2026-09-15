# 1. 固定 10 个案例

`evals/basic_cases.jsonl` 已准备 10 个唯一 `case_id`，数据集版本为 `day05-v2`。每项均有输入、`expected`、`fault`、`scripted_responses`、`preparation_status=ready`。修改案例时更新数据集版本；旧运行的 `input_snapshot` 保留在独立结果文件中。

| 案例 | 固定行为 | 预期终态 |
| --- | --- | --- |
| D05-01 | 根据输入 E1 总结营收 | completed |
| D05-02 | 调用报价工具，再引用工具 E1 | completed |
| D05-03 | 调用公司工具，再引用工具 E1 | completed |
| D05-04 | 没有利润资料 | insufficient_information |
| D05-05 | E1/E2 同期数字冲突 | insufficient_information |
| D05-06 | 工具参数为空，handler 不执行 | insufficient_information |
| D05-07 | 请求未知工具，handler 不执行 | insufficient_information |
| D05-08 | 可取消慢工具触发局部超时 | insufficient_information |
| D05-09 | 回答引用未提供的 E99 | invalid_evidence |
| D05-10 | 持续请求工具，模型轮数耗尽 | budget_exhausted |

D05-06～08 收到工具失败后返回明确的“未取得报价”，不会伪造查询成功。由于 `ResearchOutput` 要求 `completed` 至少有一条有证据的事实，三项的安全终态为 `insufficient_information`。未知工具、非法参数、E99 和循环请求直接由固定响应注入；`fault` 是测试配置，不发送给模型。所有报价和公司资料仍为本地教学 `fixture`，不是实时信息。
