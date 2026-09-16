"""D08：Manual/LangChain 固定案例对照的离线测试清单。

TODO D08-Test-7.1
    只选择 D05-02、D05-06、D05-07、D05-10；缺失或重复 case_id 时拒绝。
TODO D08-Test-7.2
    Manual 观察器正确读取模型次数、工具顺序、handler 次数、终态和消息类型。
TODO D08-Test-7.3
    LangChain 正常案例形成 Human/AI(tool_calls)/Tool/AI(final) 顺序。
TODO D08-Test-7.4
    非法参数、未知工具和重复工具只记录实际行为，不提前补 D09 安全策略。
TODO D08-Test-7.5
    两边都复用同一个 TOOL_REGISTRY；案例运行后 handler 必须恢复。
TODO D08-Test-7.6
    compare_case() 拒绝不同 case_id，并稳定输出调用次数、错误和工具顺序差异。
TODO D08-Test-7.7
    runner 默认离线；导入模块不读取 .env、不创建 ChatDeepSeek、不访问网络。
"""
