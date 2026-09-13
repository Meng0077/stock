# D03：手写工具调用循环

这些文件是练习要求，不代表功能已实现。你编写核心代码，助手负责提示和检查。

## 顺序

1. 两个本地 fixture 工具：已检查通过。
2. CompanyToolParams：模型已检查通过；案例统计需使用 expected。
3. 工具白名单：按 backend/src/stock_agent/tools/registry.py 中的要求完成。
4. [向模型声明工具](day03/04_tool_definitions.md)。
5. [解析工具调用请求](day03/05_parse_calls.md)。
6. [执行并回传结果](day03/06_return_results.md)。
7. [限制调用循环](day03/07_loop_limits.md)。
8. [记录与验收](day03/08_verification.md)。

第 4～7 步逐步写进 backend/examples/manual_agent.py，避免每一步复制一套客户端。
第 8 步的离线验证写进 backend/examples/verify_manual_agent.py。
SDK 具体字段以本地已安装版本及智谱官方工具调用文档为准。
先验证普通函数和手工构造的模型响应，再运行真实模型。

## 当前状态

- [x] 第 3 步：白名单及执行入口通过检查。
- [x] 第 4 步：工具声明可打印、字段匹配（已通过本地预览和离线模拟）。
- [x] 第 5 步：JSON 与工具参数错误被拒绝。
- [x] 第 6 步：完整工具消息往返成功。
- [x] 第 7 步：3 轮决策、4 次执行限制有效。
- [x] 第 8 步：离线验收、两项真实工具往返及最终回答人工核对均通过。记录见 [验收报告](day03/verification_report.md)。
