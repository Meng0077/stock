# 7. 取消与清理

先实现 `backend/examples/timeout_cancel.py`，再整合
`backend/examples/structured_agent.py`。按下面顺序完成。

## 按顺序完成的 TODO

- [x] **TODO 7.1，清理协程**：`async slow_work(started: asyncio.Event, events: list[str]) -> None` 通知调用者已开始，长时间等待，并在退出前向 `events` 记录 `cleanup`。入参是启动通知和事件列表；正常返回 `None`，取消时抛出 `CancelledError`。
- [x] **TODO 7.2，发起取消**：`async cancellation_demo() -> dict[str, object]` 内部创建 `started/events/calls`，用 `create_task` 启动 `slow_work`，等 `started` 后调用 `cancel()`。无入参；完成后续 TODO 后返回含 `status`、`events`、`calls`、`task_cancelled` 的字典。
- [x] **TODO 7.3，等待终态**：`cancellation_demo()` 在 `cancel()` 后 `await task`，捕获 `CancelledError` 并记录 `cancelled`；等待 `cleanup` 完成后返回含 `status/events/calls/task_cancelled` 的字典。无入参。
- [x] **TODO 7.4，无后续调用**：`cancellation_demo()` 只在 `await task` 正常返回时向 `calls` 记录 `next_call`；取消时 `calls` 为空，返回的 `task_cancelled` 来自 `task.cancelled()`。`calls` 只是检查流程的列表，不是真正的工具调用。无入参；返回含 `status/events/calls/task_cancelled` 的字典。
- [x] **TODO 7.5，离线入口**：`async main() -> None` 无入参，依次显示 `timeout_demo()` 与 `cancellation_demo()` 的返回字典，不返回业务结果。文件入口用一次 `asyncio.run(main())`，不访问网络或密钥。
- [x] **TODO 7.6，Agent 整合**：`structured_agent.py` 的 `async main(argv=None, *, events=None) -> int` 接收命令行参数和运行事件列表；仅当 `events is None` 时新建列表。正常返回退出码；取消时关闭客户端、记录 `cancelled` 并重新抛出 `CancelledError`，不返回退出码或再启动请求。
- [x] **TODO 7.7，离线验收**：`backend/tests/` 用离线假任务和假客户端验证 `cleanup`、取消传播、无悬挂任务、取消后无新调用，以及取消已完成任务不覆盖终态。测试函数不返回业务数据，只做断言。

## 验收

演示中的三个对象都由 `cancellation_demo()` 自己创建：`started = asyncio.Event()` 用来等 `slow_work` 真正开始；`events: list[str] = []` 记录 `started`、`cleanup` 等过程；`calls: list[str] = []` 只记录“是否走到下一步”。`slow_work` 只接收前两个对象，不接收 `calls`。

`calls.append("next_call")` 不是调用函数，只是写下一条记录。真实工作流里，下一步可能是 `await execute_tool(...)`，但本练习不运行真实工具。

- 取消发生在等待中时，finally 确实执行。
- 调用者观察到 CancelledError，任务最终 cancelled。
- 清理完成后没有悬挂任务或新请求。
- 取消已完成任务不会重跑其逻辑；记录最终状态不被错误覆盖。

task.cancel() 是取消请求，不代表调用时所有工作已立即停止。
本地清理客户端不代表远端请求被撤回，不保证已经发生的费用消失。
