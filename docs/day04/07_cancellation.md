# 7. 取消与清理

先实现 backend/examples/timeout_cancel.py，再整合 structured_agent.py。

## 你来完成

1. 创建一个长等待协程，在 try 中 await asyncio.sleep，在 finally 中记录清理事件。
2. 用 asyncio.create_task 启动它；稍后从调用者执行 task.cancel()。
3. 调用者必须 await task，等待取消与清理完成，并处理 asyncio.CancelledError。
4. 内部如捕获 CancelledError，只做必要记录后 raise，不能返回普通成功值或继续循环。
5. 对外运行记录可标记 cancelled，但内部取消信号必须继续传播到拥有该任务的调用者。
6. 不留未等待的后台任务。若自己创建了子任务，负责取消并等待它们结束。
7. 取消后不得开始新模型请求、工具调用或格式修复。

## 验收

- 取消发生在等待中时，finally 确实执行。
- 调用者观察到 CancelledError，任务最终 cancelled。
- 清理完成后没有悬挂任务或新请求。
- 取消已完成任务不会重跑其逻辑；记录最终状态不被错误覆盖。

task.cancel() 是取消请求，不代表调用时所有工作已立即停止。
本地清理客户端不代表远端请求被撤回，不保证已经发生的费用消失。
