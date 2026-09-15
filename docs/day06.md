# D06：FastAPI 薄接口——今日 Todo

- 日期：2026-09-15
- 预计用时：约 4 小时
- 今日主线：把 Week 1 已验证的 Manual Agent 接到 `POST /api/runs`
- 今日状态：D06 已完成；Step 1～8、手工链路和最终回归均已验收
- 参考：[Week 2 计划](week2.md)、[Python 总开发计划](../stock-agent-python-development-plan.md)

## 今天结束时要得到什么

一个同步、只读、可测试的最小 API：HTTP 请求先经过 Pydantic 校验，服务为本次运行生成 `run_id`，调用现有 Manual Agent，并只返回结构化结果或安全错误。

目标链路：

```text
POST /api/runs
    → ResearchRequest 校验
    → 生成 run_id
    → Manual Agent
    → ResearchOutput / PublicError
    → RunResponse
```

## 本日实现文件

下面文件已按实现顺序完成，并由离线测试、全量回归和一次受控手工请求验证。

1. [API 契约](../backend/src/stock_agent/api/schemas.py)：定义运行状态、内部结果和公开响应；先完成跨字段校验与映射。
2. [Manual Agent runner](../backend/src/stock_agent/agents/manual_runner.py)：定义消息构造和异步运行入口的输入、输出与异常语义。
3. [依赖边界](../backend/src/stock_agent/api/dependencies.py)：定义可替换的 `AgentRunner`，测试不得调用真实模型。
4. [FastAPI 应用](../backend/src/stock_agent/api/app.py)：定义 `new_run_id()`、`create_run()`、`create_app()` 的职责和实现顺序。
5. [契约测试](../backend/tests/test_api_schemas.py)：逐项覆盖成功/失败字段组合。
6. [路由测试](../backend/tests/test_api_runs.py)：逐项覆盖正常请求、422、超时、安全错误、密钥泄漏和导入副作用。

推荐编码顺序：`test_api_schemas.py → schemas.py → manual_runner.py → dependencies.py → test_api_runs.py → app.py`。先写当前步骤的失败测试，再完成最小代码使它通过。

## 今天不做

- [x] 未引入 LangChain；它属于 D07。
- [x] 未做数据库、Redis、任务队列、SSE、WebSocket 或后台任务。
- [x] 未做 React 页面；它属于 D10。
- [x] 未接实时行情，也未把 fixture 描述成实时数据。
- [x] 未复制第二套工具实现；继续复用现有白名单注册表。
- [x] 未把密钥、原始异常或内部堆栈返回给客户端。

## Step 0：收口 Week 1 状态（10～15 分钟）

输入：`docs/day05.md`、`docs/day05/report.md`、`docs/day05/demo.md`。

- [ ] 确认真实模型工具往返已有 `completed/pass` 记录。
- [ ] 确认 10 个固定案例的人工证据复核均已填写。
- [ ] 确认 3～5 分钟演示稿已完成并能用自己的话讲述。
- [ ] 把 `docs/day05.md` 中仍显示未完成的旧状态同步为实际结果。
- [x] 已恢复 Week 1 绿色测试基线：修复 DeepSeek/统一客户端迁移后的接口不一致、旧客户端替换点和异常吞噬问题；2026-09-15 全量测试 `98 passed`，D05 离线评估 `10/10 pass`。
- [ ] 若上述任一项实际未完成，保留未勾选并写明原因；不要仅因进入 D06 就标记完成。

产出：D05 汇总页与报告、演示稿的状态一致。

## Step 1：只学习今天必需的 FastAPI 概念（30～40 分钟）

- [x] 理解 `FastAPI()` 和 `@app.post(...)` 的职责。
- [x] 理解为什么异步 Agent 对应 `async def` 路由。
- [x] 理解请求 JSON 如何由 Pydantic 转成 `ResearchRequest`。
- [x] 观察非法请求如何自动返回 HTTP 422。
- [x] 理解测试中如何用依赖替换真实 Agent，确保不访问网络。
- [x] 能回答：HTTP 校验检查“用户请求是否合法”，Agent/Tool 校验检查“模型行为是否合法”，两层不能互相替代。

学习完成标准：能画出“HTTP → Pydantic → Agent → Response”四段链路，不需要继续扩展学习 FastAPI 的数据库、认证或部署功能。

## Step 2：补齐并锁定最小依赖（15～20 分钟）

- [x] 检查当前虚拟环境和依赖文件，不覆盖现有用户改动。
- [x] 加入并锁定 `fastapi==0.141.1`、`uvicorn==0.53.0`；测试客户端继续复用已有 `httpx==0.28.1`。
- [x] 安装后记录实际版本，确保依赖清单与环境一致；传递依赖为 `starlette==1.6.0`、`annotated-doc==0.0.5`、`click==8.5.0`。
- [x] 运行一次现有测试，确认加依赖没有破坏 Week 1 行为：`98 passed`，`pip check` 无依赖冲突。
- [x] 未安装 `langchain` 或 `langchain-deepseek`。

产出：更新后的 `backend/pyproject.toml`、运行依赖锁定文件和开发依赖锁定文件。

Step 2 记录：`requirements-dev.lock.txt` 已通过首行 `-r requirements.lock.txt` 继承新增运行依赖，因此无需重复写入；环境检查确认 `langchain_installed=False`。

## Step 3：先定义 API 契约（30～40 分钟）

建议文件：

```text
backend/src/stock_agent/api/
├── __init__.py
├── schemas.py
├── dependencies.py
└── app.py
```

- [x] 复用现有 `stock_agent.schemas.research.ResearchRequest`，不要另写一套含义重复的请求模型。
- [x] API 继续使用现有 `company_id` 字段，与领域模型和工具参数保持一致。
- [x] 定义 `RunResponse`，包含 `run_id`、`status`、`result`、`error`。
- [x] `result` 使用明确的 `ResearchOutput | None`，没有使用无约束的 `dict`。
- [x] `error` 复用现有 `PublicError | None`，只暴露固定错误码、阶段和安全提示。
- [x] 模型校验保证成功响应有 `result` 且无 `error`，失败响应有 `error` 且无伪造结果；取消状态与取消错误码必须匹配。
- [x] 同步接口契约明确：请求返回时本次运行已进入一个确定终态；契约测试 `14 passed`。

产出：API 请求/响应契约及对应单元测试。

## Step 4：把 Manual Agent 提炼成可调用的应用入口（40～50 分钟）

当前 `backend/examples/structured_agent.py` 偏命令行示例；API 不应解析命令行参数或读取打印输出。

- [x] 已把 `model_loop`、循环预算、结构化解析和终态记录抽到 `backend/src/stock_agent/agents/manual_agent.py`；CLI、评估器和 runner 共用这一份实现。
- [x] 在 `backend/src/stock_agent/agents/` 中新增一个可复用的异步运行入口。
- [x] 输入至少包含已校验的 `ResearchRequest` 和 `run_id`。
- [x] 继续复用现有 `model_loop()`、`ResearchOutput`、工具注册表、证据校验、预算和超时逻辑。
- [x] 返回结构化运行结果，不返回进程退出码，不依赖标准输出。
- [x] 把请求的 `question`、`company_id`、`data_mode`、`as_of` 正确组装进 Agent 输入；不得继续使用与请求无关的固定问题。
- [x] 在应用边界统一把已知失败转成 `PublicError`。
- [x] 未知异常只记录安全终态；不要把异常正文、请求头或 API Key 放进返回值。
- [x] 保留原 CLI 示例可运行，避免 API 改造破坏 Week 1 演示。

产出：一个 CLI 和 API 都可调用的 Manual Agent 运行函数。

Step 4 记录：模型异常映射已提炼到 `run_errors.py`，CLI 与 API runner
共用固定错误码；`model_timeout`、`total_timeout`、普通异常和取消清理均由
离线测试覆盖。当前全量测试为 `144 passed`，CLI `--preview` 可正常运行。

## Step 5：实现最小 FastAPI 应用（30～40 分钟）

建议文件：`backend/src/stock_agent/api/app.py`。

- [x] 创建 `FastAPI` 应用，不在模块导入阶段创建网络客户端或请求模型服务。
- [x] 实现 `POST /api/runs`，声明 `response_model=RunResponse`。
- [x] 每次请求生成唯一 `run_id`，并把同一个 ID 传给 Agent 和响应。
- [x] 路由只负责 HTTP、依赖注入和响应映射；不把 Agent loop 复制进路由。
- [x] 通过依赖注入提供 Agent runner，使测试能替换为离线 stub。
- [x] 正常结果保留 `data_mode` 和证据 ID。
- [x] 失败只返回现有安全错误对象，不返回原始异常。
- [x] 增加最小启动方式，并在 README 或 D06 记录中写明。

产出：可导入的 `app` 和可启动的 `/api/runs`。

本地启动（在仓库根目录执行）：

```bash
PYTHONPATH=backend/src backend/.venv/bin/uvicorn stock_agent.api.app:app --reload
```

Step 5 记录：应用工厂、路由、响应模型和 runner 依赖已经组装完成；离线
冒烟验证覆盖唯一 `run_id`、成功字段映射和未知异常脱敏。全量回归结果为
`144 passed`。完整 HTTP 边界测试仍按计划留在 Step 6。

## Step 6：先离线测试 API 边界（45～55 分钟）

建议文件：

```text
backend/tests/
├── test_api_schemas.py
└── test_api_runs.py
```

- [x] 正常请求：返回成功状态、UUID 格式 `run_id` 和结构化结果。
- [x] 连续两个请求：获得不同 `run_id`。
- [x] `question` 为空或全空格：HTTP 422，Agent runner 调用次数为 0。
- [x] `company_id` 为空：HTTP 422，Agent runner 调用次数为 0。
- [x] `data_mode` 非法：HTTP 422，Agent runner 调用次数为 0。
- [x] `as_of` 不带时区：HTTP 422，Agent runner 调用次数为 0。
- [x] 多余字段：HTTP 422，Agent runner 调用次数为 0。
- [x] Agent `model_error`：返回固定公开错误，不含原始异常。
- [x] Agent `model_timeout` / `total_timeout`：返回明确终态和固定公开错误。
- [x] 响应递归扫描：不得出现测试 API Key、Authorization、堆栈或底层异常文本。
- [x] 单独导入 `stock_agent.api.app`：Agent runner 和网络客户端调用次数都为 0。
- [x] 测试全部使用 stub/fake，不访问真实模型服务。

测试完成标准：不仅断言状态码，还断言 Agent 是否被调用、传入的 `run_id` 是否一致、错误字段是否安全。

Step 6 记录：`test_api_runs.py` 共 `20 passed`；全量回归共 `164 passed`。
测试只使用 `dependency_overrides`、fake runner 和独立导入检查，没有访问真实
模型服务。测试运行时有一条来自 Starlette 内部 AnyIO 旧别名的弃用警告，
不影响当前测试结果。

## Step 7：手工跑通一次最小链路（20～30 分钟）

- [x] 启动本地 API，并确认 `POST /api/runs` 可访问。
PYTHONPATH=backend/src backend/.venv/bin/uvicorn stock_agent.api.app:app --host 127.0.0.1 --port 8000
- [x] 发一个合法 fixture 请求，保存为 `docs/d06-step7-valid-response.json`。

curl -sS \
  -X POST http://127.0.0.1:8000/api/runs \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "NVDA",
    "question": "请查询教学模拟报价和公司介绍，并区分事实、推断和缺失信息。",
    "data_mode": "fixture",
    "as_of": "2026-09-15T16:00:00+08:00"
  }' \
  -o docs/d06-step7-valid-response.json \
  -w "HTTP %{http_code}, elapsed %{time_total}s\n"

- [x] 发一个非法请求，保存为 `docs/d06-step7-invalid-response.json`，确认得到 HTTP 422 校验结构。

curl -sS \
  -X POST http://127.0.0.1:8000/api/runs \
  -H "Content-Type: application/json" \
  -d '{
    "company_id": "NVDA",
    "question": "   ",
    "data_mode": "fixture",
    "as_of": "2026-09-15T16:00:00+08:00"
  }' \
  -o docs/d06-step7-invalid-response.json \
  -w "HTTP %{http_code}, elapsed %{time_total}s\n"


- [x] 真实模型只运行一次受控案例：provider 为 DeepSeek，模型为 `deepseek-v4-flash`，终态为 `completed`，未循环重试。
- [x] 响应保留 `data_mode=fixture` 和 E1/E2；正文明确说明是本地教学模拟数据，不是实时行情、真实报价或投资建议。
- [x] 服务已停止，并确认 `127.0.0.1:8000` 没有遗留监听进程。

产出：一条成功/明确失败的完整调用记录，以及一条 HTTP 输入校验失败记录。

Step 7 记录：合法响应生成于 2026-09-15 17:10，返回 UUID、`completed`、
结构化结果和 `error=null`；非法响应生成于 17:13，空白 `question` 在
Pydantic 边界被拒绝。API 当前不公开 token 用量，因此记录为 `unavailable`。

## Step 8：回归、文档与讲解（20～30 分钟）

- [x] 运行全量 pytest，记录通过数；不能只跑新 API 测试。
- [x] 确认已有 CLI `structured_agent.py --preview` 可运行。
- [x] 在本文件末尾填写实际完成情况、测试命令、结果、限制和待办。
- [x] 记录今天创建或修改的文件。
- [x] 能用自己的话说明路由、请求模型、Agent runner、工具白名单和输出校验各自的边界。
- [x] 未完成的 D05 历史收口项继续保留为 `[ ]`，没有为完成 D06 修改事实。

HTTP 请求
    ↓
ResearchRequest 输入校验
    ↓
FastAPI create_run
    ↓
依赖注入获得 run_manual_agent
    ↓
生成并传递同一个 run_id
    ↓
model_loop
    ↓
白名单工具
    ↓
ResearchOutput 和证据校验
    ↓
AgentRunResult
    ↓
RunResponse
    ↓
HTTP JSON 响应

## D06 最终验收清单

- [x] `POST /api/runs` 可接受合法请求并返回 `run_id` 与确定终态。
- [x] 请求结构由 Pydantic 校验，非法输入不会进入 Agent。
- [x] API 调用的是 Week 1 Manual Agent，不是 LangChain Agent。
- [x] 工具仍只有现有只读白名单入口，未知工具没有执行路径。
- [x] 模块导入不会请求网络。
- [x] 测试不请求真实模型。
- [x] 密钥、原始异常和堆栈不会进入响应。
- [x] Agent 超时、模型错误等失败路径有安全且可读的响应。
- [x] 全量回归测试通过，CLI 演示没有被破坏。
- [x] 能解释 HTTP validation 与 Agent/tool validation 为什么是两层边界。

## 今天完成后再考虑的 D07 入口

D07 才引入 LangChain，并让 LangChain Agent 复用现有工具注册表。今天不要提前迁移；D06 的 API 契约和离线测试应允许后续只替换 Agent runner，而无需重写路由或工具业务逻辑。

## 实际执行记录（完成后填写）

- 完成时间：2026-09-15。
- 新增文件：`agents/manual_agent.py`、`agents/manual_runner.py`、`agents/run_errors.py`、`api/__init__.py`、`api/app.py`、`api/dependencies.py`、`api/schemas.py`、`tests/test_api_runs.py`、`tests/test_api_schemas.py`、`tests/test_manual_runner.py`，以及两份 Step 7 响应记录。
- 修改文件：`examples/structured_agent.py`、`pyproject.toml`、`requirements.lock.txt`、`tests/test_structured_agent_runtime.py`、`evals/run_basic_cases.py` 和本文档。
- API 测试结果：`test_api_runs.py` 共 `20 passed`。
- 全量测试结果：`164 passed`；另有一条 Starlette 内部 AnyIO 旧别名弃用警告，不影响通过结果。
- CLI 验证：`structured_agent.py --preview` 正常运行。
- 手工请求结果：合法 fixture 请求 `completed`；空白问题请求返回 HTTP 422；服务已正常停止。
- 已知限制：仅验证本地 fixture 数据；同步接口不公开模型 token 用量；未引入数据库、队列、流式响应、实时行情或 LangChain。
- 遗留 TODO：D06 范围内无阻塞项；Step 0 中未核实的 D05 历史收口项保持未勾选，D07 再考虑 LangChain。
