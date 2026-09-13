# 1. 定义研究结果模型

实现位置：backend/src/stock_agent/schemas/research_output.py。

本任务只定义 D04 的研究回答模型。新版计划后续另建行情、决策、用户组合和风险模型；不要为了最终投资建议提前把它们塞进 ResearchOutput。

## 你来完成

使用 Pydantic 定义 EvidenceClaim 和 ResearchOutput：

- EvidenceClaim：text 为非空字符串；evidence_ids 为非空证据 ID 字符串列表。
- ResearchOutput：status 限定 completed / insufficient_information。
- facts：EvidenceClaim 列表，保存资料中的事实。
- inferences：EvidenceClaim 列表，保存有证据基础但仍属推断的内容。
- missing_information：非空字符串组成的列表。
- data_mode：fixture / historical / live；由程序与当前资料模式核对，不能信任模型随意标记。

所有模型拒绝额外字段，清除字符串首尾空白；注意列表元素也需要声明约束。
completed 至少有一条事实；insufficient_information 至少说明一项缺失信息，可保留已有事实。
可使用 model_validator 检查字段之间的规则，实现时查对应版本写法。
不要为必填业务字段随意设置默认值，从而把模型漏字段隐藏掉。

## 验收

正常结果、缺字段、额外字段、空 text、空证据列表、列表中空白 ID、非法 status 均有案例。
completed 没有事实应拒绝；insufficient_information 没有缺失说明应拒绝。
输出格式由 Pydantic 检查，证据 ID 是否存在由下一步业务校验负责。
