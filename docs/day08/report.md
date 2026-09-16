# D08 Manual Agent vs LangChain Agent 对照报告

> 本文件是报告模板。必须先运行四个固定离线案例，再依据实际结果填写；
> 不以代码行数推断框架优劣，不把 D09 尚未实现的安全能力写成已完成。

## 固定案例结果

| 案例 | 场景 | Manual 终态 | LangChain 终态 | 模型调用 | 工具顺序 | handler 次数 | 主要差异 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D05-02 | 正常报价 | TODO | TODO | TODO | TODO | TODO | TODO |
| D05-06 | 非法参数 | TODO | TODO | TODO | TODO | TODO | TODO |
| D05-07 | 未知工具 | TODO | TODO | TODO | TODO | TODO | TODO |
| D05-10 | 重复工具/预算 | TODO | TODO | TODO | TODO | TODO | TODO |

## 职责边界

| 对比项 | Manual Agent | LangChain Agent | 最终责任方 |
| --- | --- | --- | --- |
| 模型调用 | TODO | TODO | TODO |
| tool call 解析 | TODO | TODO | TODO |
| ToolMessage 回填 | TODO | TODO | TODO |
| tool loop | TODO | TODO | TODO |
| 工具白名单 | TODO | TODO | 应用 |
| Pydantic 参数校验 | TODO | TODO | 应用 schema |
| 业务限制 | TODO | TODO | registry/handler |
| evidence 校验 | TODO | TODO | 应用（D09 迁移） |
| budget | TODO | TODO | 应用（D09 迁移） |
| timeout/cancel | TODO | TODO | 应用（D09 迁移） |
| final schema | TODO | TODO | 应用 + framework（D09） |

## 我的结论

- LangChain 替代了：TODO
- LangChain 没有替代：TODO
- Manual 更容易观察的部分：TODO
- LangChain 减少的样板代码：TODO
- D09 必须补回的安全机制：TODO
