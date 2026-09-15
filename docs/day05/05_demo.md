# 5. 第一周演示与讲解

**TODO D05-Core-3：由你完成 3～5 分钟演示。** 输入是 D05-02（正常报价）和 D05-07（未知工具）结果文件，以及 `structured_agent.py`、`tool_calling.py`、`registry.py`。输出是填好的 `docs/day05/demo.md` 和一次自己能独立讲的演示。

推荐顺序：先声明本地 `fixture`，再展示模型工具请求 → 白名单和参数校验 → Python handler 执行 → 按 `tool_call_id` 回传 → 最终回答。然后展示未知工具的 handler 次数为 0、返回工具错误、模型承认没有报价。最后展示 pytest 的 91 个通过和人工复核仍 pending，说明为什么不能只靠提示词约束、为什么要预算。

真实模型的完整工具往返仍未验证时，只演示离线固定响应并明确说明；真实结果留给 TODO D05-Core-1。
