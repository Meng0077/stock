# Stock Agent Week 1～Week 2 面试问题与口语化答案

> 使用范围：基于本项目 D01～D07 的实际实现，以及刚开始的 D08 对照工作。
> D09 的安全机制迁移和 D10 的 LangChain API 接入还没有完成，面试时不要说成已上线。

## 一分钟项目介绍

我做的是一个只读的股票研究 Agent。这个项目的重点不是预测股价，也不是自动
交易，而是把模型调用、工具调用、结构化输出、证据校验、安全边界和 API 接口
完整串起来。

第一周我没有直接上框架，而是自己实现了 model-tool-model 循环。模型只能请求
白名单中的两个本地 fixture 工具，程序会校验工具名、参数和 tool call ID，再把
结果回传给模型。最终回答必须符合 Pydantic 定义的 `ResearchOutput`，引用的
evidence ID 也必须来自本次输入或成功的工具结果。我还加了模型轮数、工具次数、
超时、取消和安全错误处理，并用 10 个固定案例做离线验收。

第二周我先把 Manual Agent 接到 FastAPI，做成 `POST /api/runs`，然后让
LangChain `create_agent` 复用同一个 `TOOL_REGISTRY`。目前 LangChain 的真实
工具往返已经跑通，完整轨迹是 HumanMessage、带 tool calls 的 AIMessage、
ToolMessage、最终 AIMessage。现在我正在用相同固定案例对照 Manual 和
LangChain，重点分析框架替代了哪些 orchestration，以及哪些安全和业务责任仍然
必须由应用代码负责。

## Week 1～Week 2 做了什么

| 开发日 | 实际内容 | 面试关键词 |
| --- | --- | --- |
| D01 | 虚拟环境、依赖锁定、配置、首次真实模型调用、响应与错误观察 | SDK、配置安全、token、429 |
| D02 | `ResearchRequest`、Pydantic 校验、带时区时间、asyncio 基础 | 类型标注 vs 运行时校验、async/await |
| D03 | fixture 工具、参数模型、白名单 registry、Manual tool loop、调用预算 | tool call、dispatch、ToolMessage、预算 |
| D04 | `ResearchOutput`、evidence 校验、一次格式修复、超时、取消、安全错误 | structured output、证据、timeout、cancel |
| D05 | 10 个固定案例、scripted model、事件记录、自动检查与人工事实复核 | eval、可复现、故障注入、人工复核 |
| D06 | `POST /api/runs`、请求/响应契约、runner、依赖注入、安全错误映射 | FastAPI、422、run_id、薄接口 |
| D07 | LangChain Tool adapter、`create_agent`、DeepSeek 真实工具往返 | Agent runtime、ToolMessage、最小权限 |
| D08 | 正在用 D05-02/06/07/10 对照 Manual 与 LangChain | 公平比较、行为指标、职责边界 |

当前可公开的验证结果：D07 收口时全量测试为 `191 passed`；LangChain 新增测试
共 27 个。真实 LangChain 案例使用 DeepSeek 调用 `get_quote`，返回 NVDA 的
100 USD 本地教学 fixture，并明确说明不是实时行情。

## 一、项目与架构

### 1. 你这个项目解决什么问题？

口语回答：

它解决的不是“怎么让模型多说一些股票内容”，而是“怎么让模型在受控边界内完成
一次研究任务”。模型可以决定要不要调用工具，但它不能决定自己拥有哪些权限，
也不能跳过参数校验、证据校验和预算。我的目标是把不确定的模型能力和确定性的
程序规则分开，让整条链路能测试、能追踪、失败时也能安全结束。

### 2. 为什么定位成只读教学 Agent？

口语回答：

因为这是第一版，我希望先把 Agent 的协议和安全边界做扎实。项目里的报价和公司
资料都是本地 fixture，不是实时数据，也没有交易能力。这样我能稳定复现工具调用、
错误和预算行为，不会把第三方行情质量、交易权限和资金风险混进当前学习目标。

### 3. 一次正常请求经过哪些步骤？

口语回答：

HTTP 请求先由 Pydantic 校验成 `ResearchRequest`，FastAPI 为它生成一个唯一
`run_id`，然后通过 runner 进入 Agent。模型如果需要报价，会生成 `get_quote`
的 tool call。程序检查白名单、参数和调用 ID，通过后才执行 registry 中的
handler，再把 fixture 结果作为 ToolMessage 回给模型。模型生成最终回答后，
程序还要检查输出结构和证据归属，最后只返回 `RunResponse` 允许公开的字段。

### 4. 模型、框架和应用代码分别负责什么？

口语回答：

模型负责理解问题、选择工具和生成回答。LangChain 负责模型节点、工具节点、
ToolMessage 回填和循环调度。应用代码负责白名单、Pydantic 参数规则、NVDA
业务限制、fixture 标记、证据校验、预算、超时以及安全错误。简单说，框架负责
“怎么跑”，我的代码负责“允许做什么，以及结果能不能被接受”。

### 5. 为什么不能只靠 system prompt 约束模型？

口语回答：

Prompt 是软约束，不是权限系统。模型可能理解错，也可能输出不存在的工具名、
非法参数或者虚构数据，而且换模型、换版本后行为也可能变化。所以我会在 prompt
里说明规则，但真正的权限和业务限制一定放在确定性的 Python 代码里。例如模型
请求 `delete_file`，程序会在白名单层拒绝，handler 调用次数是 0。

## 二、Python、Pydantic 与异步

### 6. Python 类型标注和 Pydantic 校验有什么区别？

口语回答：

类型标注主要帮助阅读、IDE 和静态检查，运行时不会自动阻止错误数据。Pydantic
会在创建模型或者 `model_validate` 时真正执行规则。比如 `question: str` 只是
标注；`Field(min_length=1)` 加上去除空白后，才会在运行时拒绝空问题。我的项目
把外部输入和模型生成的工具参数都放到 Pydantic 边界里校验。

### 7. `ResearchRequest` 为什么需要 `AwareDatetime`？

口语回答：

`as_of` 表示本次研究允许使用资料的截止时间。如果时间没有时区，同一个字符串
在不同时区可能代表不同时间，后续做资料过滤会产生歧义。所以我直接要求带时区的
datetime，无时区输入会在 HTTP 层返回 422。现在这个字段已经进入 Agent 输入，
真正按发布时间过滤资料会在后续 RAG 阶段继续实现。

### 8. `data_mode` 有什么用？写成 fixture 就会自动变成模拟数据吗？

口语回答：

不会。`data_mode` 是数据语义和校验字段，不是数据源开关。写成 fixture 只表示
本次结果应该使用并声明本地教学数据，真正的数据仍然来自 fixture handler。
程序会核对工具结果和最终输出的数据模式，防止模型把模拟报价说成实时行情。

### 9. `async def` 调用后为什么还要 `await`？

口语回答：

调用 `async def` 只会得到一个 coroutine，并不会立刻把函数完整执行。`await`
才会等待这段异步工作完成，同时把事件循环的执行机会让给其他任务。它不是说所有
代码都会自动并发；只有相互独立的任务才适合用 `gather` 等方式并发。如果第二步
依赖第一步结果，我还是会按顺序 await。

### 10. 为什么模型客户端和 FastAPI 路由都使用异步？

口语回答：

模型请求和网络 I/O 的主要时间是在等待远端响应，用同步阻塞会浪费服务线程。
异步客户端可以在等待期间让事件循环处理其他请求。FastAPI 路由调用的是异步
runner，所以路由本身也用 `async def`，这样整条链路不需要在同步和异步之间
反复包装。

## 三、工具、Registry 与 Manual Agent

### 11. 为什么要有 `TOOL_REGISTRY`？

口语回答：

Registry 是模型请求和 Python handler 之间的确定性白名单。模型只能输出工具
名称和参数，程序再用这个名称查 registry；不在表里的名字没有执行路径。我没有
使用 `eval`、动态 import 或按任意字符串找函数，这样权限范围是代码审查时就能
看清楚的。

### 12. 一次 tool call 的完整流程是什么？

口语回答：

模型先返回工具名、JSON 参数和 `tool_call_id`。程序检查 ID、解析 JSON、确认
工具在白名单、再用 `CompanyToolParams` 校验参数。合法后执行 handler，把结果
包装成 tool 消息，并使用同一个 `tool_call_id` 回传。模型拿到工具结果后再进行
下一轮推理，直到给出最终回答或者达到停止条件。

### 13. 为什么 `tool_call_id` 很重要？

口语回答：

它相当于模型工具请求和工具结果之间的关联 ID。同一轮可能有多个工具调用，如果
结果没有带回原来的 ID，模型就不知道哪个结果对应哪个请求。我的 Manual Agent
会拒绝空 ID 和同一条消息里的重复 ID，并在事件记录和 tool message 中保留它，
这样协议和追踪都能对得上。

### 14. 为什么参数会校验两次？

口语回答：

LangChain adapter 的 `args_schema=CompanyToolParams` 会先在框架入口校验一次，
但 adapter 仍然调用统一的 `execute_tool()`，registry 在应用边界再校验一次。
第二次不是为了依赖 LangChain，而是保证其他调用方，比如 Manual Agent，直接走
registry 时也有相同保护。这样业务入口本身是安全的，不会因为换了框架就失去校验。

### 15. 参数格式合法，为什么 AAPL 仍然会失败？

口语回答：

Pydantic 只负责判断参数结构是不是合法，比如 `company_id` 是否为非空字符串。
AAPL 在格式上完全合法，但当前业务只提供 NVDA fixture，所以 handler 会再做
业务判断并拒绝。这个例子正好说明 schema validation 和 domain validation 是
两层不同的边界。

### 16. 为什么要限制模型轮数和工具次数？

口语回答：

Agent 可能持续请求工具，形成无限循环并不断消耗时间和 token。我在 Manual
Agent 中限制最多 3 个模型轮次、4 次工具执行。D05-10 专门让模型重复请求工具，
最后得到 `budget_exhausted`，而不是继续运行。预算是应用策略，不能假设框架默认
值就等于我的业务预算。

### 17. `result_sink` 是什么？为什么不直接依赖返回值？

口语回答：

`model_loop()` 最早保留了命令行式状态码返回值，但 API runner 还需要最终消息和
结构化结果。`result_sink` 是调用方传入的可变容器，循环结束时把 `messages` 和
`final_output` 写进去；`events` 则保存运行过程和 `run_finished`。runner 可以从
这些结构化数据构造 API 结果，不需要解析 stdout。后续如果重构接口，我会考虑
直接返回一个明确的运行对象，减少多出口状态。

## 四、结构化输出、证据与错误处理

### 18. 为什么有了 JSON prompt 还要 `ResearchOutput`？

口语回答：

Prompt 只能要求模型尽量输出 JSON，不能保证字段齐全、类型正确或者字段之间语义
一致。`ResearchOutput` 会在运行时检查 status、facts、inferences、
missing_information 和 data_mode。只有解析与校验通过，结果才能进入后续流程。
所以 structured output 是“模型生成加程序验收”，不是一句 prompt 就完成了。

### 19. 为什么格式修复最多只允许一次？

口语回答：

完全不修复会让偶发格式错误直接失败，但无限修复又可能形成新的循环和费用风险。
所以我做了一个折中：第一次结构校验失败时，把安全的错误位置和 schema 回给模型，
只允许修正一次，而且这次请求也计入模型轮数和总超时。第二次还失败就明确结束，
不会一直重试。

### 20. evidence ID 校验能证明回答正确吗？

口语回答：

不能。它只能证明模型引用的 ID 确实来自本次输入或者成功的工具结果。例如 E1 是
合法 ID，但模型仍可能把 E1 里的 100 USD 写成 120 USD，程序只看 ID 是发现
不了的。所以我把自动结构检查和人工事实复核分开：自动检查协议与归属，人工检查
数字、单位、时间和句子是否真的被证据支持。

### 21. 为什么要区分 facts、inferences 和 missing information？

口语回答：

研究回答里最危险的问题之一，是把推断说成事实，或者在缺资料时硬给答案。分开
以后，事实必须有证据，推断也要说明依据，缺失信息则明确告诉用户当前不能确认
什么。这不是保证模型绝对正确，但能让输出更容易验证，也方便后续做自动规则和
人工复核。

### 22. 你设计了哪些超时？

口语回答：

我区分了模型单次请求超时、工具单次执行超时和整个任务总超时。它们对应的失败
阶段不同，不能全部叫“超时”。局部工具超时后可以形成工具错误结果；任务总超时
则必须停止整个运行。除此之外还有模型轮数和工具次数预算，它们限制的是次数，和
墙钟时间不是一回事。

### 23. 如何处理取消？

口语回答：

`asyncio.CancelledError` 不能像普通异常一样吞掉，我会显式重新抛出，让取消向上传播。
同时通过异步上下文管理器关闭 HTTP 客户端，并测试取消后不会继续请求模型或执行
工具。取消不是普通失败，如果吞掉它，调用方可能以为任务结束了，但后台还在继续
消耗资源。

### 24. 为什么不把原始异常直接返回给前端？

口语回答：

原始异常可能包含供应商响应、内部路径、请求信息，甚至意外带出敏感内容。我的
应用边界会把已知失败映射成固定的 `PublicError`，只公开错误码、阶段和安全提示。
日志也尽量使用固定文案，不把异常正文直接拼进去。前端需要的是可处理的错误语义，
不是底层堆栈。

### 25. 你怎么区分 `run_finished` 和 `final_output`？

口语回答：

`run_finished` 是事件流里的终态，说明这次 run 是 completed、failed、cancelled
还是 information insufficient，并可带安全错误。`final_output` 放在
`result_sink`，只有模型最终输出通过结构和证据校验后才存在。runner 会按同一个
`run_id` 找终态，再读取 final output；两者缺失或矛盾时会降级为安全的
`model_error`，不会猜一个成功结果。

## 五、评估与测试

### 26. 为什么要用 scripted model，而不是所有测试都调用真实模型？

口语回答：

真实模型有随机性、网络波动和费用，也会随供应商升级改变行为，不适合作为每次
提交都必须稳定通过的单元测试。scripted model 可以精确控制下一条响应是正常
tool call、非法参数、未知工具还是重复调用，因此可以确定性地覆盖失败路径。真实
模型我只保留少量受控验收，用来证明集成链路确实能跑通。

### 27. D05 的 10 个案例覆盖了什么？

口语回答：

它们包括正常总结、报价工具、公司资料、缺少资料、证据冲突、非法参数、未知工具、
工具超时、伪造 evidence ID 和重复工具导致预算耗尽。每个案例都有固定输入、固定
模型响应和预期终态。错误案例得到预期错误也算测试通过，比如 `invalid_evidence`
被正确拦截，不代表分析成功。

### 28. 离线 10/10 能说明模型质量好吗？

口语回答：

不能。它只能说明在固定响应下，程序的协议、安全规则和终态符合预期。它不能证明
真实模型每次都会选择正确工具，也不能证明回答事实正确。所以报告里会明确区分
offline scripted 结果和 real API 结果，token 不可用时写 null，而不是写成 0。

### 29. 自动测试和人工复核分别负责什么？

口语回答：

自动测试适合检查 schema、工具 ID、白名单、参数、调用次数、资料模式和 evidence
ID 是否属于允许集合。人工复核负责判断句子语义是否真的受到证据支持，包括数字、
单位、报告期、冲突处理和是否把 fixture 误写成实时行情。两者不是互相替代，而是
分别覆盖确定性规则和语义正确性。

### 30. 你的测试如何保证不访问网络？

口语回答：

单元测试使用 fake client、scripted response 和 LangChain fake chat model，
不会创建 `ChatDeepSeek`。FastAPI 测试通过依赖覆盖替换真实 runner，模块导入测试
也会确认不会读取配置或创建客户端。真实模型脚本单独放在 examples 中，必须显式
运行，而且关闭自动重试。

## 六、FastAPI 边界

### 31. 为什么 FastAPI 路由要保持薄？

口语回答：

路由只应该负责 HTTP 输入、依赖注入、调用 runner 和响应映射。如果把 tool loop、
证据校验和模型客户端生命周期都写进路由，CLI、测试和以后替换 LangChain 都很难
复用。我把应用逻辑放在 runner，把协议放在 schema，这样 D10 切换 Agent runner
时不需要重写 HTTP 层。

### 32. HTTP 422 和 Agent 错误有什么区别？

口语回答：

422 表示用户请求在进入 Agent 前就不合法，例如空 question、非法 data_mode 或
无时区的 as_of，这时 runner 调用次数应该是 0。Agent 错误发生在请求已经合法
以后，例如模型超时、未知工具或最终输出不合法。HTTP validation 管用户输入，
Agent/tool validation 管模型行为，两层不能合并。

### 33. 为什么使用依赖注入？

口语回答：

FastAPI 的 `Depends` 让我把 Agent runner 当成可替换依赖。生产环境注入真实
runner，测试里注入 fake runner，所以路由测试可以验证 run_id、响应和错误映射，
完全不请求模型。它也为 D10 从 Manual runner 切换到 LangChain runner 留出了
清晰接缝。

### 34. `run_id` 有什么作用？

口语回答：

它是一次运行的身份，HTTP 响应、Agent 事件、终态和最终结果都应该使用同一个 ID。
每个请求生成新的 UUID，runner 返回的 ID 如果和路由生成的不一致，我会把它当成
内部错误，而不是返回错配数据。以后做异步任务、日志追踪或持久化时，这个 ID 也是
串联整条链路的基础。

### 35. 为什么响应还需要 Pydantic 模型？

口语回答：

请求校验只能保证输入，不能保证内部代码一定返回安全结构。`RunResponse` 约束成功
时必须有 result 且没有 error，失败时必须有 error 且不能夹带伪造结果，取消状态
也要和错误码一致。这样响应模型是最后一道公开边界，防止内部 dict 随意泄露出去。

## 七、LangChain 与 Manual Agent

### 36. 为什么先写 Manual Agent，再用 LangChain？

口语回答：

先手写让我真正理解模型请求、tool call、消息回填、循环和停止条件，而不是只会调
一个框架 API。迁移到 LangChain 后，我能具体指出它替代了哪些代码，也能看出哪些
业务安全机制并不会自动出现。这种学习顺序让我不会把 framework convenience
误认为 system safety。

### 37. LangChain `create_agent` 替代了哪些代码？

口语回答：

它主要替代了模型和工具之间的 orchestration。Manual 版本里我自己写 while、
读取 `message.tool_calls`、分发工具、构造 role=tool 的消息，再 continue 回模型。
LangChain 里这些由 model node、tool node、ToolMessage 和 graph edge 处理。工具
内部仍然调用我自己的 registry 和 handler。

### 38. 你如何把现有工具接到 LangChain？

口语回答：

我写了很薄的 `@tool` adapter，使用现有 `CompanyToolParams` 作为 args schema。
adapter 不直接调用业务 handler，而是 await 统一的 `execute_tool(tool_name,
arguments)`。所以 LangChain 和 Manual Agent 共享同一个 registry、参数清理和
fixture 数据，没有维护两套业务实现。

### 39. 为什么 `build_langchain_agent` 允许白名单子集？

口语回答：

白名单表示“最多允许什么”，不代表每次都必须把所有工具给模型。按最小权限原则，
只查报价时可以只提供 `get_quote`。我的组装函数允许 canonical adapter 的无重复
子集，同时拒绝未知工具、重复工具和名字相同但对象不是原 adapter 的冒名工具。
如果以后某个 Agent 永远固定使用全部工具，也可以去掉 tools 参数，在内部组装。

### 40. LangChain 的消息轨迹是什么样？

口语回答：

真实验证里我看到的是 `HumanMessage → AIMessage(tool_calls) → ToolMessage →
AIMessage(final)`。第一次 AIMessage 表示模型决定调用 `get_quote`，ToolMessage
是 Python adapter 返回的 fixture，最后一条 AIMessage 才是用户看到的回答。
一次 Agent `ainvoke` 通常对应两次模型请求，不能把它误解成一次 HTTP 调用。

### 41. 用了 LangChain 后，白名单和 Pydantic 还需要吗？

口语回答：

需要，而且更应该明确。LangChain 可以根据 schema 帮我解析和调用工具，但它不
知道业务上只允许 NVDA，也不能替我决定哪些工具应该暴露。我的 adapter 只是一层
协议适配，真正的允许集合和业务规则仍在应用层。框架升级或者换模型时，这些确定性
边界也不会跟着丢失。

### 42. Manual 和 LangChain 哪个更好？

口语回答：

我不会简单说谁绝对更好。Manual 版本透明、容易学习和定制错误语义，但编排代码
多，维护成本也高。LangChain 减少了标准 tool loop 的样板代码，生态也更完整，
但默认行为不一定等于我的业务策略，所以要额外验证。我的选择是保留 Manual 作为
教学和行为基线，主应用后续使用 LangChain，同时共用一套业务工具。

### 43. D08 为什么使用相同 scripted cases 比较？

口语回答：

如果两边都直接请求真实模型，随机性、网络和模型版本会干扰比较，很难判断差异来自
框架还是模型。所以 D08 复用 D05-02、06、07、10 的输入和 scripted decisions，
并让两边使用同一个 registry。比较指标是模型调用次数、工具顺序、handler 次数、
消息轨迹、终态和错误，不比较代码行数。

### 44. D08 当前完成了吗？

口语回答：

目前 D08 已经建立共同 observation、离线 runner、测试和报告骨架，最终四案例
对照还在实现中。我可以讲清比较方法和预期关注点，但不会把未运行的表格说成真实
结果。已经确认的事实来自 D07：正常工具往返成功，非法参数不会进入 handler，
未知工具没有授权执行路径。

## 八、工程取舍、问题与下一步

### 45. 从智谱切换到 DeepSeek 时遇到了什么？

口语回答：

最明显的问题不是改一个 base URL，而是旧代码里混有供应商 SDK 的响应类型、调用
层级和异常处理。我后来把模型访问抽成 provider-neutral 的 `LLMClient`，使用统一
的 Pydantic response schema，并让 provider 配置决定 base URL 和必要参数。
迁移后我还通过全量测试修复了旧客户端替换点、异步调用和异常吞噬造成的问题。

### 46. 为什么锁定依赖版本？

口语回答：

Agent 框架、Pydantic 和模型 integration 更新都比较快，不锁版本很容易出现同一
代码今天能跑、明天接口变化。项目同时保留直接依赖和解析后的锁定文件，并运行
`pip check`。这样测试结果能和具体版本对应，排查问题时也知道是代码变化还是依赖
漂移。

### 47. 项目里最有价值的失败案例是什么？

口语回答：

我觉得未知工具和合法 evidence ID 但语义错误这两个最有价值。未知工具说明模型
不是权限主体，即使它请求危险名称，程序也不能执行。合法 ID 但内容错误则说明
结构校验不是事实校验，自动化边界必须说清楚。这两个案例让我避免把“格式正确”
误认为“结果可信”。

### 48. 目前项目最大的限制是什么？

口语回答：

现在只有 NVDA 的本地 fixture，没有真实行情、数据库、RAG 或交易执行；LangChain
也还没有接入生产 FastAPI runner。D07 只验证了标准工具循环，Manual Agent 已有
的 timeout、budget、evidence 和安全错误还要在 D09 明确迁移。这个限制是有意的，
因为我先保证边界可测试，再逐步增加数据和功能。

### 49. D09 准备做什么？

口语回答：

D09 会把 `ResearchOutput`、证据校验、模型和工具超时、任务总超时、调用预算、
取消以及安全错误语义整合进 LangChain 路径。重点不是假设框架已经替我处理，而是
为每个失败建立明确终态和测试矩阵。比如 invalid args、unknown tool、重复调用和
伪造 evidence 都要有可观察且安全的结果。

### 50. D10 准备做什么？

口语回答：

D10 会把 FastAPI 的 runner 从 Manual Agent 切到完成安全迁移的 LangChain
Agent，同时保持 HTTP 契约和工具业务逻辑不变。之后再做最小 React 结果页，把
run_id、结果、来源和错误展示出来。路由保持薄，所以理论上只需要替换依赖提供的
runner，不需要重写整个 API。

### 51. 如果要把它做成生产系统，你还会补什么？

口语回答：

我会先补真实数据源的来源追踪、按 company 和 as_of 过滤、持久化运行记录、认证、
限流、可观测性和离线评估门槛。如果加入交易能力，还需要把研究和执行彻底隔离，
增加账户权限、幂等、风控、人工确认和审计。不会因为 Agent 能生成 tool call 就直接
给它资金操作权限。

## 常见追问的短回答

### 为什么 `event.get("type")` 不直接写 `event.type`？

因为 event 是普通字典，不是对象，所以没有 `.type` 属性。`event["type"]` 在字段
必须存在时更严格，缺失会抛 `KeyError`；`event.get("type")` 在扫描混合事件、允许
字段缺失时更安全，会返回 `None`。

### `@classmethod` 是什么？

它把第一个参数从实例 `self` 变成类 `cls`，适合写替代构造器或者只依赖类配置的
方法。这个项目的响应映射可以用 classmethod，因为它是“从另一个对象构造当前
响应模型”，不需要先有一个响应实例。

### 为什么 fixture 要返回字典副本？

防止调用方修改共享常量。如果直接返回同一个字典，一个测试把 company_id 改掉，
后面的请求也会被污染。返回 copy 可以保持案例互相隔离和结果可复现。

### token 用量不可用时为什么不是 0？

0 表示确定没有消耗，`None` 或 unavailable 表示供应商或 fake model 没有提供数据。
把未知写成 0 会让成本和评估指标失真。

### 为什么真实验证关闭自动重试？

学习阶段需要看到第一次失败的真实语义。如果 429 被库自动重试后成功，我可能误以为
这次调用没有失败，也无法准确记录请求次数和费用。生产环境可以再设计有限、可观察、
带退避的重试策略。

## 面试时不要说过头

- 不要说“这是实时股票 Agent”；目前是本地 fixture。
- 不要说“支持自动交易”；目前只读，没有交易 handler。
- 不要说“LangChain 自动解决了安全问题”；它主要解决标准 orchestration。
- 不要说“evidence ID 合法就证明事实正确”；语义仍需核对。
- 不要说“离线 10/10 证明模型准确率 100%”；它证明固定案例下程序行为符合预期。
- 不要说“Week 2 已全部完成”；当前 D08 在进行，D09/D10 尚未实现。
- 不知道具体数字时可以说 unavailable，不要编造 token、耗时或通过率。

## 三分钟回答顺序

如果面试官让你完整讲项目，可以按下面顺序说：

1. 定位：只读教学股票研究 Agent，不是实时行情或交易系统。
2. 主链路：请求校验 → 模型决策 → 白名单工具 → ToolMessage → 结构化结果 → 证据校验。
3. Week 1：手写循环，理解协议、预算、超时、取消和评估。
4. Week 2：FastAPI 薄接口，再把工具接入 LangChain，保持同一个 registry。
5. 安全边界：prompt 是软约束，程序控制白名单、参数、业务规则和公开错误。
6. 验证：scripted 离线案例保证可复现，少量真实请求证明集成，人工复核补语义判断。
7. 取舍：LangChain 接管 orchestration，但 D09 仍要迁移安全策略，D10 再接主 API。

最后可以用这一句收尾：

> 这个项目让我真正理解了 Agent 不是“模型加几个函数”，而是一个不可信决策者和
> 确定性权限、校验、预算、证据及错误边界共同组成的系统。
