# D02：请求校验与异步基础

## 运行方法

在项目根目录，使用已激活的虚拟环境：

```bash
python backend/examples/validate_request.py
python backend/examples/async_basics.py
```

Pydantic 2.13.5 已随 SDK 安装，今天将它明确声明为直接依赖；版本快照无需变更。
两个脚本不读取密钥、不请求模型。D01 的 hello_model.py 仍独立运行，尚未接入此请求模型。

## 阅读顺序

1. `backend/src/stock_agent/schemas/research.py`：BaseModel 定义规则，Field 限制长度，Literal 限制可选值，AwareDatetime 要求时区。
2. `backend/examples/validate_request.py`：字典进入 model_validate，成功得到 ResearchRequest，失败抛出 ValidationError。
3. `backend/examples/async_basics.py`：调用 async def 得到协程，await 等待执行结果，gather 调度并发，asyncio.run 提供事件循环入口。

## 三层边界

- 普通 Python 类型标注供阅读和静态检查使用，不会自动在运行时拒绝错误类型。
- Pydantic 在实例化/校验时执行规则；会把合法的日期字符串转成带时区的 datetime。本示例不是全局严格模式。
- 业务校验还需要确认公司、资料来源和时间。as_of 只是本次研究的资料截止时间字段，今天没有实现资料过滤；live 标签也不会自动提供真实行情。

只有财报时，不能把模型生成的价格当作报价。输入格式通过，不等于内容有证据。

## 你来动手

- [ ] 运行校验案例，解释为什么全空白问题也被拒绝。
- [ ] 加入 question=None 的失败案例，并确认错误发生在 question。
- [ ] 将 question 最大长度临时改成 10，观察原来的正常案例为什么失败，随后恢复。
- [ ] 运行异步练习，先预测“开始/完成”的打印顺序，再对照输出。
- [ ] 将两个模拟等待都改成 2 秒，预测并观察顺序约 4 秒、并发约 2 秒，随后恢复。
- [ ] 用自己的话回答：调用 async def 后发生了什么？await 为什么不等于阻塞整个事件循环？

asyncio.sleep 模拟非阻塞 I/O 等待。不要用 time.sleep 替换后还期待相同并发效果。
只有相互独立的工作才适合这里的并发；若第二步需要第一步结果，应先 await 第一步。

## 验收记录

助手已在当前虚拟环境运行：13/13 校验案例符合预期；顺序等待 3.00 秒，并发等待 2.00 秒；两个脚本正常退出，未调用模型。用户动手练习与解释待完成。

参考：[Pydantic 模型](https://docs.pydantic.dev/latest/concepts/models/)；[Python 3.11 协程与任务](https://docs.python.org/3.11/library/asyncio-task.html)。
