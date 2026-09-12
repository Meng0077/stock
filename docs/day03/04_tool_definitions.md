# 第 4 步：向模型声明工具

实现位置：backend/examples/manual_agent.py。

## 你来完成

1. 定义 build_tool_definitions() -> list，声明 get_quote 和 get_company_profile。
2. 每个工具声明包含 type="function"，以及 function 下的 name、description、parameters。
3. parameters 使用 CompanyToolParams.model_json_schema() 生成，避免手写规则与本地校验不一致。
4. 描述明确写出：只读工具、当前仅支持 NVDA、返回本地 fixture 数据；报价不是真实行情。
5. 复用 D01 的密钥读取方式和智谱国内客户端，在 create 请求中传入 tools。
6. 用户问题先使用“请查询 NVDA 的教学模拟报价和公司介绍”。系统要求不得将模拟结果描述为实时行情。

## 提示

- 工具声明只是一份 JSON 数据，不包含可执行的 Python 函数。
- 注册表中的 handler 不可直接放入发给模型的 JSON。
- 模型提出调用请求，真正执行函数的是后续的 Python 代码。
- 核对已安装 SDK 对 tools、tool_choice 的支持后使用；不要求每次都强制调用工具。
- 保留 --preview 入口，只打印 messages 和 tools，不读出或显示密钥、不访问网络。

## 验收

- 两个声明名称与 TOOL_REGISTRY 完全一致。
- parameters 中存在必填 company_id，且禁止额外字段。
- 预览能序列化为 JSON，无函数对象。
- 尚未完成工具回传时，不把第一次返回的工具请求当成最终回答。
