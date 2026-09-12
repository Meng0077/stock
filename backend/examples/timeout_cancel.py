"""D04 离线动手练习，详见 docs/day04/05_timeouts.md、07_cancellation.md。

TODO：asyncio.sleep 模拟快/慢工具。
TODO：单工具 asyncio.timeout 与外层任务总时限。
TODO：create_task -> cancel -> await -> 观察 CancelledError。
TODO：用 finally 记录清理，验证取消后无新调用。
TODO：用 asyncio.run(main()) 启动；不使用密钥，不访问网络。

当前只有任务说明，运行不会执行任何验证。
"""
