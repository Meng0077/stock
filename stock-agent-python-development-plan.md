# AI 辅助美股研究 Agent · Python 开发计划

- 版本：v3.3，2026-09-25；聚焦财报 RAG、行情与技术分析、宏观数据和 Market Reaction 四条核心研究链路。
- 定位：面向 Agent 开发岗位的可演示项目；模型负责理解问题、调用只读工具、检索资料和解释结果，行情、宏观、市场反应与决策规则由可复现的 Python 模块完成。
- 排期：面试版 9 周、45 个开发日、约 180 小时；按每天 4 小时、每周 5 天估算。若 Python 异步、数据源接入或部署比预期慢，另留 1–2 周缓冲。
- 当前进度：D11–D15 已完成本地 RAG、通用 Knowledge Tool、SEC Provider、HTML 解析和任意 ticker 的首次按需索引，见对应 day 文档；中文检索、SEC 历史清单及无匹配资料的细分原因等已记录遗留项继续保留。D16 已完成 PostgreSQL / pgvector 的原文、chunk、embedding 和索引快照持久化。D17 已完成 exact snapshot、latest compatible snapshot、按 accession 增量更新和历史检索时间边界。D18 已完成最小 SEC Company Facts、Financial Tool、精确数值存储及 Financial / Knowledge evidence 组合校验。D21 已完成 MarketDataProvider、Quote / Bar 契约和离线 Fixture 验收。D22 已完成 Longbridge 适配器、离线测试及 NVDA / AMD 真实在线验收。D24 已完成 CPI、PPI、PCE、就业、Claims、Fed / SEP 和美债核心链路、基于供应商 Forecast 的非 PIT Estimated Surprise、Macro Tool 及 evidence 校验，并通过离线测试、真实 Provider 和真实模型 Agent 端到端验收；严格 PIT Surprise、历史 vintage 回放和可靠实际发布时间不在首版范围。D19、D20 延后。

本文是拟开发计划。目录、接口和演示能力只有在代码实现并验收后才算完成；不能把 fixture、历史数据或延迟数据标成实时行情。

## 1. 首版目标与边界

首版支持用户询问任意美股公司的 ticker，无需提前把该公司加入白名单或准备资料。系统按问题选择行情、结构化财务、宏观数据、市场反应或公司文档；公司文档不存在于本地时按需获取并索引，已有索引可复用并增量更新。系统结合最新可获得的报价、技术结构、已发布的宏观事件、事件后的实际市场表现以及公司资料，给出有依据的条件性研究判断。

一次完整结果应包含：数据截至时间、资料来源、事实与推断、技术面判断、宏观实际值与预期差、已观察到的市场反应、反对理由、失效条件，以及资料不足时的明确停止。模型的文字解释不能覆盖程序计算出的数值、时间边界或 Guard 结论。

首版不固定支持的公司数量，也不预先为全市场建库。保留一个行情提供方、日线及最新报价、一个结构化财务来源（先使用 SEC XBRL Company Facts），以及覆盖通胀、就业、FOMC、SEP 和美债收益率的宏观数据。D26 起按 Market Reaction 的实际需要接入历史分钟行情，不提前扩大 D22 的范围。日线历史需满足 MA50 等指标的窗口要求，默认请求至少 60 个已完成交易日，不能只取近几天。SEC 为公司文档的首个 Document Provider；一次只获取当前问题范围内必要的 filings。少量固定股票和 fixture 仅用于学习与可复现评估，不能成为产品的公司白名单。

“任意 ticker”指可以提交未预置的美股公司代码，并动态解析和查询；数据可用性由各提供方实际覆盖决定。无效代码、无法匹配发行人、无可用 filing 或供应商缺少数据时，分别返回明确的缺失原因。不能因本地没有索引就拒绝该公司，也不能用其他公司的数据补齐。美股上市的外国发行人需考虑 20-F、40-F、6-K 等资料，不能只找 10-K/10-Q。首版按单用户本地演示设计；多用户身份、授权和账户隔离需另行实现与验收。

首版没有用户组合管理、个人风险建议、订单提交、自动交易、PaperBroker、券商写权限或收益承诺。新闻检索与事件影响路径分析暂缓。回测、模拟成交、订单状态机、券商接入和完整自动交易工程进入第二阶段。

### 1.1 各类信息走不同路径

| 信息 | 获取方式 | 主要校验 |
| --- | --- | --- |
| 报价、日线历史 | 市场数据提供方的结构化接口 | 交易所覆盖、事件时间、接收时间、是否延迟、窗口长度、缺 K 线与复权口径 |
| 技术指标与关键价位 | Technical Analysis Engine → 确定性计算 TechnicalContext | 已完成 K 线、计算窗口、确认时间、计算版本、候选价位依据与缺失指标 |
| 营收、利润等精确财务指标 | Financial Tool → 结构化财务提供方，先接 SEC Company Facts | 指标口径、币种和单位、报告期、累计与单季口径、filing 及修订版本 |
| 宏观发布 | BLS、BEA、FRED 等结构化接口和发布日程 | Actual、Previous、Consensus、Surprise、统计期、发布时间、来源与修订状态；不能称为实时跳动指标 |
| 宏观 Market Reaction | MacroReleaseEvent + 历史分钟行情 + MarketReactionEngine | 事件时间可靠性、交易时段、参考价、观察窗口、行情缺口、基准可用性；只描述实际变化，不宣称因果 |
| 业务说明、风险因素、管理层讨论等文档内容 | Knowledge Tool → Document Provider → 按需索引 → 检索 | 公司、filing、报告期、可用时间、版本、证据 ID、原文是否支持结论 |

RAG 用于非结构化资料和可追溯引用；报价、K 线、精确财务指标、宏观数据和 Market Reaction 从结构化接口与确定性计算读取，不让模型从文章中猜精确数字。Market、Financial、Knowledge、Macro 和 Market Reaction 各自保持独立来源与时间语义，模型按问题组合调用。

### 1.2 任意 ticker 的按需索引

```text
retrieve_knowledge(company_id, question)
    ↓
ensure_company_index(company_id) ← 任务上下文中的 as_of
    ↓
Document Provider：ticker → 发行人 / CIK → 截至 as_of 可用的 filings
    ↓
检查本地索引
    ├─ 无索引 → 获取必要文档 → 解析 → chunk → embedding → indexing
    ├─ 文档与索引配置一致 → 复用
    └─ 有新增 filing / 修订 → 仅索引新增或变化文档
    ↓
Persistent Vector Store → 按发行人和时间过滤 → retrieve
    ↓
本次实际返回的片段与 evidence_id
```

Agent 只使用 `retrieve_knowledge(company_id: str, question: str)`，不接触本地文件名、SEC 下载细节或 VectorStore。Day12 内部使用本地 fixture；后续替换为 ensure_company_index 和真实 Provider，Agent 的调用接口保持一致。company_id 在工具边界接受规范化 ticker，内部用 CIK 标识 SEC 发行人；行情仍按证券 ticker 查询，不能把不同股类的报价合并。

索引按需建立，首次询问未预置公司时允许产生下载与索引开销；相同 `as_of` 的 exact snapshot 直接复用，较晚 `as_of` 的请求先检查 filing 清单，再从历史 snapshot 增量更新。初始文档范围明确限制为截至 as_of 最近的年报、最近的可用中期报告及问题需要的近期披露，记录实际覆盖范围；历史问题按所问报告期选择资料，不只查当前最新文件。6-K 等披露不能一律当作季度财报。

Freshness 以 Provider 返回的可用 filing 清单与本地已索引清单比较，记录检查时间；“最新”指声明的文档范围内截至任务 as_of 的可用版本。新增 accession 才触发新增文档处理；修订文件保留独立版本。未变文档不重复下载、分段或生成向量。Embedding 或分段配置变化时重建受影响索引，失败或只完成部分导入不能被标记为最新可用索引。索引是可重建的本地缓存，原文、版本和引用仍需保留。

### 1.3 Agent 与确定性分析模块的职责

1. LangChain Agent 识别用户意图，调用白名单只读工具，并决定是否需要检索更多证据。
2. Knowledge Tool 内部负责索引检查、必要的获取和更新；检索层返回本次实际提供的文档片段及证据 ID，应用层校验引用归属和资料时间。
3. Technical Analysis Engine 根据已验证的报价和 K 线计算 TechnicalContext；MarketReactionEngine 根据可靠的宏观事件时间与历史分钟行情计算不同观察窗口的实际收益和基准差异。
4. Decision Engine 使用 TechnicalContext、MacroSnapshot 和可选 MarketReaction，通过固定规则生成市场观点和 Decision Trace。分数只是规则分数；未经校准不能称为获利概率。
5. 模型把上述结构化结果解释给用户，不得改变工具数值、时间边界或 Guard 结论。宏观 Surprise、技术观点和已观察市场反应分别表述；市场反应不能被解释为已证明的因果关系。

### 1.4 数据时间与保密边界

每个外部输入至少记录 source、data_mode、event_at 或统计期、published_at（如适用）、received_at 和任务 as_of；所有具体时间带时区。研究只使用截至 as_of 已可获得的信息；历史评估不能把后来发布的宏观数据、财报修订或模型知识伪装成当时已知。

API 密钥、数据库凭据和供应商令牌不进入模型上下文、响应或日志。首版不保存用户账户和持仓，不提供个人风险阈值或仓位建议。

### 1.5 技术分析与决策的衔接

```text
Market Data：Quote + 已完成 Bars
    ↓
Technical Analysis Engine → TechnicalContext
    ↓
Macro Data → MacroSnapshot → 可选 MarketReaction
    ↓
MarketContext → Guards → Trend / Momentum / Level Factors
    ↓
DecisionResult：市场观点、关键价位、反对理由、失效条件、Trace
    ↓
Agent 调用并解释；不得覆盖 Guard 或改写结构化数值
```

首版以日线技术结构为主：5 / 20 日变化、MA5 / MA20 / MA50、ATR14、成交量变化、已确认 swing high / low，以及由这些高低点产生的 support / resistance candidates。候选价位保留产生它的 K 线和规则，不能称为必然有效的支撑或阻力。参考价格标明来自最新报价还是最近完成日线收盘，及其对应时间；日线结果不能冒充分钟级盘中结构。

用户给出“221.8 怎么看”这样的价格时，先识别标的并区分该价格是用户指定的情景价还是有来源和时间的实际报价；情景价可用于计算距离，但不能冒充当前市场价格。支撑 / 压力和失效条件由程序产生，模型只解释其依据和适用周期。

计算约定在 D23 固定并记录版本：收益变化按完成日线收盘计算，均线使用简单移动平均，ATR14 使用 Wilder 平滑并固定初始化方式，成交量与此前 20 个完成交易日均量比较。swing 初版使用左右各两根完成日线确认，固定同价处理规则；确认时间为右侧第二根 K 线完成时刻，历史 as_of 之前未确认的拐点不能使用。按最近已确认高低点比较 higher high / higher low 等结构，无法确认时明确缺失。支撑 / 阻力候选按参考价上下的位置选择，并记录价格距离和 ATR 距离；距离不等于突破概率。

所有指标使用一致的 OHLC 复权口径，并记录成交量调整方式。与当前报价比较的价位需处于可比价格尺度；缺窗口、缺交易日或拆股口径不一致时标记受影响指标不可用，不让模型补数值。

VWAP 在提供方有合适分钟数据后再增加，必须声明交易时段、session 起止和覆盖完整性。若用分钟 OHLCV 近似计算，明确公式与近似属性；仅有日线时标为不支持，不推算盘中 VWAP。Gap 可后续用一致口径的开盘 / 前收盘数据扩展；Volume Profile 和更复杂市场结构暂不纳入首版必做，不增加开发周数。

## 2. 技术栈与运行方式

| 层 | 首版选择 | 职责 |
| --- | --- | --- |
| 前端 | React + TypeScript | 输入研究问题，展示证据、数据时间、技术指标、宏观发布、Market Reaction 和 Decision Trace |
| API | FastAPI + Pydantic | 请求校验、只读研究任务接口、错误与结果契约 |
| Agent | LangChain Python | 模型、工具、结构化输出、调用预算和事件记录 |
| 工作流 | 小范围 LangGraph | 取数、检索、校验、决策、解释的条件分支和一次 checkpoint 演示 |
| RAG | Document Provider + 按需索引 + 关键词 / Embedding / pgvector | 动态发行人解析、索引复用与增量更新、元数据过滤、引用定位和固定评估 |
| 数据 | 一个行情适配器、SEC 文档及 Company Facts、BLS / BEA / FRED 等宏观接口 | 各工具独立取数，统一标的、来源、数据模式和时间字段 |
| 技术分析 | Python 确定性计算 | 收益、均线、ATR、成交量、确认拐点、候选关键价位与 TechnicalContext |
| 市场反应 | Python 纯函数 | 宏观事件与分钟行情时间对齐、观察窗口收益、市场基准对比与数据质量状态 |
| 决策 | Python 纯函数 / 显式规则 | 聚合 TechnicalContext、MacroSnapshot 和可选 MarketReaction，输出市场观点、失效条件和 Decision Trace |
| 存储 | PostgreSQL + SQLAlchemy；向量阶段使用 pgvector | 发行人映射、filing / 索引状态、原文和片段版本、向量、研究结果和评估；按阶段引入 |
| 验证 | pytest + 固定评估案例 | 规则、权限、检索、证据、时间和完整链路检查 |

手写 Manual Agent 保留为教学对照；D06 之后的主应用使用 LangChain，不能复制两套各自维护的工具业务逻辑。LangGraph 只围绕确实需要条件分支和 checkpoint 的步骤使用；首版不承诺多 worker 可靠领取、复杂人工审批或任意进程故障恢复。

API 可先同步返回完整结果，随后根据演示需要加有限的流式事件。若实现持久任务或 SSE，run_id、事件顺序、取消与重连语义必须一起验证；单靠 asyncio.create_task 不等于跨进程持久任务。

## 3. 每周里程碑

| 周次 | 开发日 | 本周核心 | 可演示成果 |
| --- | --- | --- | --- |
| 第 1 周 | D01–D05 | 模型调用、Pydantic、Manual Agent、结构化输出与验收 | 可复现的命令行 Agent 和失败案例 |
| 第 2 周 | D06–D10 | FastAPI 薄接口与 LangChain 迁移 | 同一只读工具在手写和框架 Agent 中通过契约案例 |
| 第 3 周 | D11–D15 | 保留 RAG 基础与 Tool 接入；真实 Provider、解析和按需索引 | 未预置 ticker 首次查询能获取必要文档并返回原文片段 |
| 第 4 周 | D16–D20 | 持久化复用、增量更新、工具组合和检索评估 | 重启后复用索引；新增 filing 只增量处理；固定案例有错误分析 |
| 第 5 周 | D21–D25 | 行情、TechnicalContext、MacroSnapshot 与时间校验 | 技术指标和宏观发布可复核，行情与宏观时间边界清楚可见 |
| 第 6 周 | D26–D30 | 宏观事件与 Market Reaction | 宏观发布与分钟行情可靠对齐，观察窗口收益和基准差异可复算 |
| 第 7 周 | D31–D35 | 可复现的多维市场分析引擎 | 技术面、宏观与市场反应分别可追溯，结构化研究结论可复现 |
| 第 8 周 | D36–D40 | 小范围 LangGraph 与 React 工作台 | 四条核心研究链路按需运行，网页展示与取消恢复路径可演示 |
| 第 9 周 | D41–D45 | 集成评估、故障演示、部署与面试讲解 | 可从干净环境启动并完成 5–8 分钟面试演示 |

前端任务已提取为独立并行开发线，详见 `docs/frontend-development-plan.md`。当前可在 D08/D09 期间基于公开 API 契约与 mock 完成 FE01/FE02；真实 API 联调在 D10 收口，后期引用、数据时间、Decision Trace、MacroSnapshot 与 Market Reaction 界面继续受对应后端契约约束。

每天约 30 分钟阅读、150 分钟实现、45 分钟验证、15 分钟记笔记。排期按交付物推进；不要把未通过的任务因为日期到了就标为完成。

## 4. 分日任务

### 第 1 周：保留当前学习进度

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D01 | 模型 SDK、虚拟环境、配置和首次真实调用 | 可重复请求，能解释输入、响应、用量与失败路径；记录见 docs/day01.md |
| D02 | Pydantic 请求模型与 asyncio 基础 | 正常和非法输入有案例；能说明协程何时执行；记录见 docs/day02.md |
| D03 | 两个只读 fixture 工具、注册表、手写工具循环和预算 | 非法工具不能执行；工具调用 ID 往返、3 轮 / 4 次限制与真实请求已验收，见 docs/day03.md |
| D04 | 结构化输出、证据归属、格式修复、超时与取消 | 完成 docs/day04.md 的离线与真实验证；不能把 TODO 当完成 |
| D05 | 10 个固定案例及人工事实复核 | 每个案例有明确终态，自动规则检查与人工证据复核分开，见 docs/day05.md |

D04/D05 的未验收项继续按对应文档追踪，不因进入 RAG 阶段而标为完成。D04 的 ResearchOutput 和 EvidenceClaim 是研究回答模型；后面新增市场、宏观与 Market Reaction 模型，不要求现在把所有领域对象塞进一个 schema。

### 第 2 周：FastAPI 与 LangChain

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D06 | 定义研究请求、run_id、状态和安全错误；建 FastAPI 薄入口 | 输入错误可读，导入模块不会请求网络，密钥不返回给客户端 |
| D07 | 把现有注册表工具接入 LangChain；保持只读白名单 | 工具参数由 Pydantic 校验，未知工具无执行路径 |
| D08 | 在相同固定案例上比较 Manual Agent 和 LangChain Agent | 轻量 runner、四案例验证与报告已完成；记录状态、错误、工具顺序与消息差异，不统计调用次数；独立 runner 测试未补，脱稿复盘待自检（见 docs/day08.md） |
| D09 | 整合结构化输出、预算、超时和事件记录 | 原标准：无 choices、截断、非法 JSON、虚构引用和预算耗尽均有明确终态。核心整合、截断保护和运行事件已验证；无 choices／非法 JSON 的 LangChain 专项验收按用户要求遗留，不标记全部完成（见 docs/day09.md） |
| D10 | 跑通 CLI / API 的最小研究路径，建立 React 对话式研究页骨架 | 用户只输入自然语言；一个请求有结构化结果、来源和运行身份；失败不会泄露原始异常 |

周门槛：不是只把旧函数包上 @tool；能说明模型提出工具请求、框架执行工具和应用校验输出分别发生在哪里。

### 第 3 周：RAG 基础与真实资料按需获取

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D11 | 保留 Document → Chunk → Embedding → Vector Store → Retriever 本地基础练习 | 基础链路已跑通；公司过滤与 evidence_id 已验证，中文检索失败如实保留，见 docs/day11.md。来源时间 / 版本 / hash 元数据接入按用户要求暂缓至真实资料阶段 |
| D12 | 将通用 retrieve_knowledge(company_id, question) 接入现有 Tool 注册表和 LangChain Agent | fixture 接入已完成；检索 → ToolMessage → Agent → ResearchOutput 跑通，本次引用归属与无资料路径已验证。256 项自动测试和四个真实模型案例通过，见 docs/day12.md；不代表真实按需索引已完成 |
| D13 | 实现 SEC Document Provider：ticker 解析、CIK 映射和 filing 发现 | ticker / CIK、recent filing 发现、美国及外国发行人表单与修订、带时区的 accepted_at / as_of 筛选已实现；保留报告期、accession、主文档和来源 URL。历史清单读取、无匹配资料的具体原因按用户要求遗留，不标记全部完成，见 docs/day13.md |
| D14 | 下载必要 filing，解析与清洗正文，并保留引用上下文 | 限定范围内已完成：SEC HTML 主文档、6-K HTML EX-99 附件选择、标题与表格文字清洗、嵌套表格、来源元数据、接受时间、版本身份、内容 hash、不支持格式、空正文，以及 block 字符范围和 XPath 已实现并验证；其他附件明确不覆盖，见 docs/day14.md |
| D15 | 实现 ensure_company_index：首次查询不存在索引时才获取、分段和嵌入 | 已完成主体：未预置 ticker 可首次建索引；相同配置且时间边界兼容时在进程内复用。文档内容、解析器版本、分段和 Embedding 模型进入可追踪身份；证据返回来源 URL，SEC 证据标记 historical。精确 block/XPath 对外回查遗留；跨进程持久化留在 D16，freshness 留在 D17，见 docs/day15.md |

周门槛：Day12 的 Agent 接口保持不变，Day15 可在内部切换到真实 Provider；未预置公司无需新增工具或修改公司列表。用户可回到证据原文；“命中一个 ID”和“句子受证据支持”分开检查。

SEC 接入通过后端完成，按官方要求声明 User-Agent 并遵守访问频率限制；只获取所需资料，不批量扫描全市场。Submissions、XBRL 与访问约束见 [SEC API 文档](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)和 [EDGAR 访问说明](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)。

### 第 4 周：持久化索引、增量更新与评估

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D16 | 将原文、filing 清单、索引状态、片段与向量存入 PostgreSQL / pgvector | 已完成：原文、block、chunk、embedding 和 company index snapshot 已持久化；模型、revision、维度、parser 和分段配置进入索引身份，引用可以回到保存的原文，见 docs/day16.md |
| D17 | 实现 Freshness 检查和新增 filing / 修订的增量更新 | 已完成核心范围：exact snapshot 直接复用；没有 exact 时从更早的同配置 snapshot 做 SEC metadata diff；无新增只写新 snapshot，有新增只处理新增文档和向量；修订 accession 不覆盖历史证据；索引和检索同时遵守 as_of。固定验收与边界见 docs/day17.md |
| D18 | 明确 Market / Financial / Knowledge Tool 独立边界；接入最小结构化财务查询 | SEC Company Facts 先提供少量精确指标，保留单位、报告期和 filing 来源；Agent 能组合财务指标与文档证据。行情先复用现有 fixture，真实行情在 D21–D25 接入；Macro 与 Market Reaction 分别在 D24、D26–D30 接入，未接入能力明确标记 |
| D19 | 建关键词基线，准备开发集 / 保留集及必需证据标注 | 关键词与向量使用同一资料版本和过滤条件；案例覆盖公司、中文问题、报告期、冷启动、复用、增量与无资料；实现一个简单混合检索对照 |
| D20 | 计算 Recall@k、引用可访问率，并人工复核事实支持 | 对关键词、向量和混合结果给出原始计数与失败分析；检查精确指标的口径。记录首次索引与复用耗时，不捏造检索提升或全市场覆盖比例 |

周门槛：使用一个未预置公司展示首次索引、重启后的复用，再用固定新增 filing 样例展示增量更新。相同 `as_of` 的 exact snapshot 可直接复用；从更早 snapshot 服务较晚请求时不能省略 freshness 检查。检索能运行不代表全部问题都能回答。

### 第 5 周：行情、技术分析与宏观

本周保留 D21–D25。D24 继续完成 MacroSnapshot 的真实数据联调，D25 同时检查行情和宏观数据的时间有效性，为下一周市场反应计算打好基础。

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D21 | 定义 MarketDataProvider、Quote 和 Bar 契约，支持动态 ticker | 区分 fixture、historical、live；明确行情时间、延迟、交易时段、周期、K 线完成状态和复权口径；证券 ticker 与发行人 CIK 分离 |
| D22 | 接入真实报价及至少 60 个已完成交易日的日线 | 未预置 ticker 可动态查询；保存事件时间和接收时间；正确处理休市、延迟、历史不足及不支持的标的 |
| D23 | 实现 Technical Analysis Engine 与 TechnicalContext | 计算 MA5/20/50、ATR14、近期变化、成交量、已确认高低点和支撑阻力候选；使用固定 OHLCV 样例验证；不使用未来或未完成 K 线 |
| D24 | 构建基于发布事件的宏观数据模块 | 接入 CPI、PPI、PCE、就业、Claims、FOMC、SEP 和美债收益率；统一 Actual、Previous、Consensus、Surprise；构建 MacroReleaseEvent 与 MacroSnapshot；完成真实数据及离线验收 |
| D25 | 建立数据新鲜度、时间有效性与缺失检查 | 识别过期报价、缺失 K 线、窗口不足、未来数据、未经验证的宏观发布日期及预期数据；受影响的分析必须降级或停止 |

第六周需要的历史分钟数据在 D26 接入，不提前扩大 D22 的开发范围。首版不为“实时”购买特定数据套餐做假设；实际 feed、交易所覆盖和延迟能力按选定供应商核对并记录。

### 第 6 周：宏观事件与市场反应

本周用 Market Reaction 替换原新闻模块，回答一个具体问题：宏观数据发布之后，NVDA、QQQ 和相关市场变量实际上发生了什么变化？

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D26 | 接入历史分钟 K 线，定义 IntradayBar 和 MarketReaction 所需行情契约 | 支持 1m 或其他已知粒度，明确盘前、盘中、盘后覆盖情况；保留时间戳、时区、数据源和交易时段；无法取得分钟数据时明确标记能力缺失 |
| D27 | 建立宏观发布事件与行情的时间对齐 | 将 CPI、PPI、非农、PCE 等 MacroReleaseEvent 与目标股票行情关联；区分计划发布时间和实际发布时间；日期精度不足时不计算分钟级反应 |
| D28 | 实现 MarketReaction 纯计算引擎 | 计算事件前参考价、T+5m、T+30m、T+1h 和收盘收益率；明确基准价格、实际交易时间、跨盘前与正常交易时段的处理规则 |
| D29 | 加入市场基准对比与历史事件查询 | 支持 NVDA、QQQ 及可用的行业 ETF；计算目标股票收益率与基准收益率之差；可查询近期同类宏观发布的历史反应 |
| D30 | 完成 MarketReaction 离线验收与真实联调 | 验证盘前发布、交易时段切换、休市、行情缺口、时间错位、未来数据、基准数据缺失；至少使用一个真实宏观事件完成端到端分析 |

MarketReaction 的核心输入输出为：

- `MacroReleaseEvent`：发布事件、实际数据、预期差、已确认的事件时间；
- `MarketDataProvider`：NVDA、QQQ 和行业 ETF 的历史分钟行情；
- `MarketReactionEngine`：时间对齐、参考价、各观察窗口收益率和基准对比；
- `MarketReaction`：可复核的市场观察结果及数据质量状态。

FRED 只返回某次经济数据发布的日期，并不足以独立支持 T+5m 计算；必须取得可靠的事件时间。市场反应只描述事件前后的实际变化，不能把同时发生的价格变化直接判定为该事件造成的因果影响。美债收益率如果目前只能获取日线，就先展示日度变化，不伪装成发布后五分钟的反应。

### 第 7 周：可复现的市场分析引擎

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D31 | 定义 MarketContext、FactorOpinion 和 DecisionResult | 聚合 Quote、TechnicalContext、MacroSnapshot 和可选 MarketReaction；记录数据来源、版本及 as_of；明确各模块缺失时的输出状态 |
| D32 | 实现 TrendFactor、MomentumFactor、LevelFactor | 复用 D23 的计算结果，使用固定阈值和确定性的规则；避免高度相关的技术信号重复计分 |
| D33 | 实现 Guard → Factors → Decision 纯函数流程 | 检查行情有效性、指标完整性及数据时间；宏观和 MarketReaction 作为独立研究上下文，缺失时不得编造或强行填充 |
| D34 | 生成 Decision Trace、反对理由和失效条件 | 每条技术面结论都能追溯指标、阈值及价格来源；宏观实际值、预期差和已观察市场反应分别表述 |
| D35 | 与 LangChain Agent 整合，完成多维市场研究演示 | 支持“NVDA 当前走势如何”“CPI 发布后 NVDA 有什么反应”“目前有哪些关键价位”等问题；Agent 不能改写工具返回的数值或覆盖 Guard |

这一周不创建复杂的“宏观利好利空评分系统”。宏观事件、技术因子和市场反应先各自输出可追溯的分析，再由 Agent 组织解释。首版的“置信分数”仅为事先定义的规则分数，不能表述为涨跌概率或胜率。

### 第 8 周：工作流与 React 界面

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D36 | 建立 LangGraph 状态及取数、检索、校验、分析、解释节点 | 财报 RAG、行情、宏观和 MarketReaction 按问题按需调用；证据不足时最多补查一次，然后明确结束 |
| D37 | 加入 Checkpoint、取消及恢复演示 | 可以取消长时间任务，恢复时明确区分已完成和需要重跑的节点；旧任务结果不能覆盖新任务 |
| D38 | 完善 React 对话界面与结构化研究结果展示 | 支持动态 ticker；展示行情时间、技术指标、财报引用、宏观统计期及数据质量提示 |
| D39 | 展示技术面、宏观与市场反应可视化 | 展示均线、关键价位、失效条件、宏观 Actual/Consensus/Surprise、市场反应观察窗口及基准对比 |
| D40 | 完成端到端工作流验收 | 演示正常研究、财报缺失、宏观数据缺失、分钟行情不可用、过期数据及任务取消场景 |

界面中的市场反应先用简单表格和折线图，不开发复杂的专业交易终端。如果增加 SSE，持久事件与临时 token 分开处理；断线后读取快照，不把不完整文本当成最终对象。

### 第 9 周：评估、部署与面试展示

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D41 | 固定模型、提示词、资料、行情、宏观数据及规则版本 | 离线案例可复现；真实 API 测试与固定样例测试分开记录 |
| D42 | 汇总 Agent、RAG 及市场分析评估结果 | 分别评价工具选择、引用支持、财务数值准确性、技术指标计算、宏观 Surprise 匹配和市场反应计算 |
| D43 | 验证关键故障和数据时间边界 | 覆盖无效 ticker、无财报、未来资料、过期报价、宏观发布前数据泄漏、时间错位、盘前行情缺失和未验证 Consensus |
| D44 | 完成 README、部署配置及干净环境启动 | 能通过文档安装运行；密钥不写入代码；明确支持的数据源、交易时段、历史范围及尚未实现的功能 |
| D45 | 完成 5–8 分钟项目演示、架构图与模拟面试问答 | 展示 Agent → 财报 RAG / 行情 / 宏观 → MarketReaction / 市场分析引擎 → 结构化解释的完整流程 |

第 9 周原则上不新增业务功能。

### 最终范围

| 模块 | 首版安排 |
| --- | --- |
| 财报 RAG 与结构化财务数据 | 保留 |
| 实时或延迟行情、日线与技术分析 | 保留 |
| 宏观数据与 Surprise | 保留 |
| 宏观 Market Reaction | 新增 D26–D30 |
| 可复现市场分析引擎 | 保留 |
| LangGraph 与 React 界面 | 保留 |
| 新闻检索、事件提取和影响路径分析 | 暂缓 |
| 用户仓位、个人风险和假设加仓 | 暂缓 |
| 券商下单与自动交易 | 不在首版范围 |

调整后，D24 提供结构化宏观发布，D26–D30 计算发布后的真实市场表现，D31–D35 将其与技术面、财报证据组合，后两周完成工作流和验收。整个计划保留 Agent、RAG、真实数据集成、可复现计算和前后端交互的技术展示重点，同时避免把项目扩大成财经新闻平台或个人交易管理系统。

## 5. 接口、领域模型与数据

### 5.1 首版接口草案

| 方法与路径 | 用途 | 关键检查 |
| --- | --- | --- |
| POST /api/chat/runs | 从自然语言创建对话式研究 | 消息校验、标的识别、服务端 as_of/data_mode、信息不足路径 |
| POST /api/runs | 创建已归一化的研究任务 | 问题、标的、资料截止时间、身份和预算；保留现有教学与评估契约 |
| GET /api/runs/{run_id} | 读取结果快照 | 任务身份、最新状态和版本 |
| GET /api/runs/{run_id}/events | 可选事件订阅 | run_id、seq、断线后快照重建 |
| GET /api/evidence/{evidence_id} | 查看引用原文 | 来源、公司、文档版本和访问范围 |
| GET /api/evaluations/{evaluation_id} | 查看固定评估结果 | 数据集、模型和规则版本 |

首版不定义下单、撤单、订单查询或券商写权限接口。任意 URL 抓取不开放给模型；导入器使用允许的来源并校验输入。

Agent 的只读工具边界：

| 工具 | 职责 | 实现阶段 |
| --- | --- | --- |
| retrieve_knowledge(company_id, question) | 非结构化资料与本次 evidence_id；内部确保所需索引可用 | D12 用 fixture，D13–D17 接真实 Provider、持久化和更新 |
| get_quote / get_price_bars(company_id) | 精确报价、日线和时间属性 | 已有报价 fixture，D21–D25 接真实市场数据 |
| evaluate_market(company_id) | 内部取行情、计算 TechnicalContext 并执行 Decision Engine，返回关键价位、市场观点和 Trace；任务 as_of 由应用上下文传入 | D23 完成技术计算，D31–D35 完成决策与 Agent 接入 |
| get_financial_metrics(company_id, 指标, 报告期) | 结构化财务数值、单位和口径 | D18 接最小 SEC Company Facts 查询 |
| get_macro_snapshot(as_of) | 截至 as_of 的结构化宏观发布、政策和收益率曲线 | D24 接真实 Macro Provider 与确定性计算 |
| get_market_reaction(company_id, release_id) | 宏观事件后的观察窗口收益和基准差异 | D26–D30 接分钟行情、时间对齐与 MarketReactionEngine |

工具命名不带特定公司。公司解析、按需索引和 freshness 属于工具内部实现；任务 as_of 由应用层上下文传入。请求 data_mode 是应用层访问策略，单条证据模式由实际 Provider 产生，最终模式从回答引用的证据反推，不能由模型绕过或传入底层改变资料性质。fixture 工具仍可限定教学资料，但真实 Provider 不能沿用只允许 NVDA 的判断。宏观文档与公司 filings 分开标识，不伪造所属公司；当前 None 宏观过滤保留为本地练习。

### 5.2 关键领域对象

| 对象 | 必要内容 | 主要业务校验 |
| --- | --- | --- |
| ResearchOutput | status、facts、inferences、missing_information、data_mode | 本次证据 ID、资料模式与事实支持 |
| CompanyIdentity | 查询 ticker、规范 ticker、发行人 CIK、公司名、来源 | 未预置代码可解析；不同股类可共享发行人文档，报价仍分别查询 |
| FilingDocument | CIK、accession、form、主文档及必要附件、报告期、接受 / 可用时间、来源、版本与 hash | 获取范围与任务匹配；修订和原文独立可追踪，文档位置可回查 |
| CompanyIndexState | 发行人、已索引文档版本、索引配置、覆盖范围、检查时间与完成状态 | 配置匹配才复用；未完成的索引不冒充最新；未来 filing 不进入历史研究 |
| Quote / Bar | 标的、价格或 OHLCV、币种、event_at、received_at、source、feed | 数据时效、交易时段、完整 K 线 |
| TechnicalContext | 标的、as_of、分析周期、参考价格及时间、行情版本、复权口径、指标及窗口、确认拐点、候选支撑 / 阻力、缺失项、计算版本 | 完成 K 线与确认时间符合截止要求；窗口足够；关键价位有原始 K 线依据；日线与分钟数据能力明确区分 |
| IntradayBar | 标的、粒度、OHLCV、event_at、source、session | 时区和交易时段明确；缺口、未来数据和粒度不匹配可识别 |
| MarketContext | Quote / Bars、TechnicalContext、MacroSnapshot、可选 MarketReaction、相关财务证据、数据版本和 as_of | 技术计算与决策使用同一行情快照；各类来源保持独立，缺失项由 Guard 判断 |
| FinancialMetric | 指标、taxonomy / concept、数值、单位、币种、报告期、filing、来源和可用时间 | 年度、单季与累计口径不混用；缺少对应指标时明确缺失 |
| MacroReleaseEvent | 发布类型、统计期、Actual、Previous、Consensus、Surprise、release_date / released_at、source | 只使用已发布数据；计划时间与实际时间分开；预期和实际正确匹配 |
| MacroSnapshot | as_of、近期发布、Fed policy / SEP、美债收益率和 warnings | 不泄漏未发布数据；单个 Provider 失败可返回部分结果并记录缺失 |
| MarketReaction | release_id、标的、参考价、T+5m / T+30m / T+1h / 收盘收益、基准差异和质量状态 | 只在可靠事件时间和可用行情下计算；交易时段、缺口和基准缺失明确 |
| DecisionResult | market_view、factors、guards、关键价位、反对理由、失效条件、trace、rule_version | 规则可复现；缺数据不强行输出方向；关键价位与 TechnicalContext 一致 |
| RecommendationResult | 市场观点、事实、推断、来源、反对理由、失效条件与缺失信息 | 模型不得改写结构化结果；市场反应不表述为确定因果 |

Pydantic 校验字段和类型；应用层继续检查证据归属、资料发布时间、报价新鲜度、宏观事件时间、分钟行情覆盖和 Market Reaction 质量状态。精确数值采用 Decimal / 数据库 NUMERIC，并固定前后端序列化方式。

### 5.3 目录与持久化

| 路径 | 职责 |
| --- | --- |
| backend/src/stock_agent/agents/ | LangChain Agent 与 Manual Agent 对照 |
| backend/src/stock_agent/tools/ | 白名单只读工具和注册表 |
| backend/src/stock_agent/retrieval/ | 复用 D11 代码；Document Provider、按需索引、分段、持久化检索和引用，不再新建平行 knowledge 包 |
| backend/src/stock_agent/market_data/ | 报价、日线、时间和来源适配 |
| backend/src/stock_agent/technical/ | D23 确定性指标、确认拐点、关键价位候选与 TechnicalContext；按需创建 |
| backend/src/stock_agent/financial_data/ | SEC Company Facts 结构化财务指标与口径归一化 |
| backend/src/stock_agent/macro/ | 基于发布事件的宏观数据、计算与 MacroSnapshot 组装 |
| backend/src/stock_agent/market_reaction/ | 宏观事件与分钟行情对齐、观察窗口收益和基准对比 |
| backend/src/stock_agent/decision/ | 因子、Guard 和 Decision Trace |
| backend/src/stock_agent/workflows/ | 小范围 LangGraph 工作流 |
| backend/src/stock_agent/api/ | FastAPI 请求与响应 |
| backend/src/stock_agent/storage/ | 资料、研究结果、市场快照、宏观发布、市场反应和评估持久化 |
| frontend/src/ | React 输入、引用、技术面、宏观、Market Reaction 与决策展示 |
| backend/tests/、evals/、docs/ | 确定性测试、固定评估和面试资料 |

目录随开发日逐步创建，不预建空包；Provider 与索引协调逻辑先放在现有 retrieval 模块内，不额外搭建索引服务。存储至少区分 runs / run_results、company_identities / filings / index_states、document_revisions / chunks / embeddings、market_snapshots / intraday_bars / financial_metrics / macro_releases / market_reactions。没有新闻、组合、风险、订单或模拟成交表。

SEC 文档用发行人 CIK、accession、文档名和内容版本标识；片段引用另包含分段版本与原文位置。Embedding 配置版本参与向量索引身份；同一份未变文档在同一配置下只嵌入一次，不因不同 ticker 指向同一发行人而重复索引。程序重启后仍可打开历史回答对应的证据版本。

HTTP 客户端在合适生命周期内复用；异步数据库 session 按请求或任务隔离。模型日志只保存允许的事件、用量、结果引用和安全错误，不保存密钥、账户号、原始异常或隐藏思维链。

## 6. 评估与验收口径

1. D05 原有 10 个工具与格式案例继续保留。新增案例覆盖检索、引用、行情延迟、宏观发布时间、宏观发布前数据泄漏、事件与行情时间错位、盘前分钟行情缺失和基准数据缺失。
2. RAG 记录固定 k 下的证据 Recall@k、引用可访问率和人工抽查的句子支持率。关键词、向量、混合路径使用相同问题和资料版本比较。
3. Agent 记录工具选择、参数合法性、调用预算、停止条件、输出结构、模型用量和耗时。Manual Agent 与 LangChain 的对照以行为为准，不以代码行数为准。
4. 技术分析、Market Reaction 与决策模块用固定输入做确定性测试；同一快照、事件、行情版本和规则版本必须得到同一结果。模型解释若与结构化 Guard 或计算结果冲突，整体结果不能通过验收。
5. 历史样例只用该时点已发布资料。实时接口样例与离线 fixture 分开标记；无法证明的数据新鲜度不写成实时。没有完整回测时，不报告策略收益率或胜率。
6. 面试报告保留失败案例，不用一组演示问答充当完整评估。样本小就给出原始计数和局限，不捏造提升比例。
7. 任意 ticker 能力必须用未预置公司验收：无需编辑股票列表，首次查询完成按需索引；再次查询和重启后不重复下载或嵌入未变文档。用记录的 Provider 输入计数验证实际复用，不只看响应更快。
8. 固定样例覆盖同一发行人的不同股类、外国发行人适用表单、无效 ticker、无 filing、报告期错误、新增 filing、修订与索引配置变化。只处理应更新文档；更新失败、部分索引和资料不足均有明确结果。
9. 分别验证 Market / Financial / Knowledge / Macro / Market Reaction 工具选择。精确财务和宏观数值不能由 RAG 摘要替代，Market Reaction 不能脱离可靠事件时间和行情计算。首次获取和复用耗时分开记录；离线评估固定 filing 与宏观事件版本，不能让真实 freshness 更新改变资料版本。
10. 技术分析使用固定 OHLCV 样例复核收益、均线、ATR 初始化、成交量窗口、拐点确认、价位选择和距离；覆盖历史不足、缺交易日、拆股口径、同价拐点、未完成 K 线与未来确认时间。Market Reaction 覆盖盘前发布、交易时段切换、休市、行情缺口、时间错位、未来数据和基准缺失。Agent 的价位、宏观数值、观察窗口收益和失效条件必须与结构化结果一致。

## 7. 后续阶段：模拟与自动交易

首版交付后，再单独规划 PaperBroker、历史回放与费用 / 成交假设、券商模拟账户、订单意图与状态机、额度预留、幂等、对账、恢复和停用开关。先验证只读账户与持仓，再决定是否接入模拟下单；真实交易权限是更后的独立决策，不由面试版通过自动推导。

自动交易阶段必须区分“发起请求”“券商受理”“部分成交”“撤单请求”和“撤单已确认”。提交超时不代表订单未发生；重试前需查询和对账。历史回测还需处理数据可用时间、复权、交易日历、费用、滑点和未来数据穿越。没有足够证据时不设定固定完成日期或宣称收益。

## 8. 面试演示与讲解重点

演示顺序：输入一个本地无索引的美股公司 ticker → LangChain Agent 调用通用 Knowledge Tool → Provider 获取必要资料并首次索引 → 展示可打开的原文证据 → 重复查询 / 重启后复用索引 → 用固定新增 filing 样例展示增量更新。再结合行情、结构化财务和 MacroSnapshot，展示一个真实宏观事件后的 Market Reaction、技术分析、Decision Trace 和结构化解释；保留过期行情、宏观时间不足或分钟行情不可用的失败分支。

准备说明：

- 手写工具循环与 LangChain 的边界：框架做了什么，白名单、预算与业务校验仍由谁负责。
- RAG 的关键词基线、向量 / 混合检索、过滤顺序和支持性评估。
- 为什么不用全市场预建库；Document Provider、ensure_company_index、持久化缓存与增量更新分别做什么，首次查询成本与复用如何验证。
- ticker 与发行人 CIK 的区别；为什么 SEC 文档检索、结构化财务、行情、宏观与 Market Reaction 要走不同工具。
- LangGraph checkpoint 与业务结果存储的区别，以及首版没有实现的多 worker 恢复。
- 为什么报价、宏观数值和 Market Reaction 不交给模型猜；为什么 FRED 的日期不能单独支持分钟级事件反应。
- 为什么事件后的价格变化只能描述为市场反应，不能直接声称是宏观事件造成的因果影响；规则分数不能直接称为收益概率。
- 为什么首版没有交易接口，未来接单前还需要状态机、幂等、对账和独立验证。

## 9. 官方资料

具体 SDK 和框架版本在实施当天核对并锁定；下列链接用于确定接口与语义，不代表任何外部服务已接入。

| 主题 | 资料 |
| --- | --- |
| LangChain Agent 与工具 | [Agents](https://docs.langchain.com/oss/python/langchain/agents)、[Tools](https://docs.langchain.com/oss/python/langchain/tools) |
| RAG 与评估 | [知识库 / 检索教程](https://docs.langchain.com/oss/python/langchain/knowledge-base)、[RAG 评估](https://docs.langchain.com/langsmith/evaluate-rag-tutorial) |
| SEC 文档、发行人映射及结构化财务 | [Submissions / XBRL APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)、[ticker / CIK 与开发者说明](https://www.sec.gov/about/webmaster-frequently-asked-questions)、[EDGAR 访问要求](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) |
| LangGraph 持久化 | [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) |
| Pydantic 与异步 | [Models](https://pydantic.dev/docs/validation/latest/concepts/models/)、[asyncio Tasks](https://docs.python.org/3/library/asyncio-task.html) |
| 行情接口示例 | [最新报价](https://docs.alpaca.markets/us/reference/stocklatestquotesingle-1)、[历史 K 线](https://docs.alpaca.markets/us/reference/stockbarsingle-1) |
| 宏观发布 | [BLS 数据 API](https://www.bls.gov/developers/)、[BEA API](https://apps.bea.gov/api/)、[FRED API](https://fred.stlouisfed.org/docs/api/fred/) |
| Market Reaction | 行情提供方的历史分钟 K 线文档、交易时段与时区说明；实际提供方在 D26 锁定后补充 |

## 10. 面试版交付清单

- [ ] 现有 D01–D05 有对应真实 / 离线验收记录；未完成任务仍标为未完成。
- [x] Manual Agent 与 LangChain Agent 共用只读工具契约，并有固定案例对照（D08 轻量 runner 与报告已完成）。
- [x] D11 本地 RAG 基础链路跑通，已记录中文检索失败；不代表真实按需索引已完成。
- [x] Day12 通用 Knowledge Tool 接入统一注册表与 Agent，本次引用归属及无资料路径通过验证（见 docs/day12.md）。
- [ ] 未预置 ticker 可动态解析并按需获取资料，无需增加公司白名单。
- [x] 原文、索引状态和向量持久化；重复查询及重启后复用，新增 filing / 修订增量更新可验证（D16 / D17 核心验收完成，生产并发与完整 SEC 历史范围仍按对应文档边界处理）。
- [ ] RAG 有小型资料集、关键词基线、向量 / 混合对照、证据定位与评估报告。
- [ ] Market / Financial / Knowledge / Macro / Market Reaction 工具独立；报价、日线、分钟行情、精确财务、宏观发布和市场反应均有来源、时间与数据模式。
- [ ] Technical Analysis Engine 输出可复核的收益、均线、ATR、成交量、确认拐点和候选关键价位；明确分析周期、窗口、时间与缺失项，VWAP 按分钟数据能力提供。
- [ ] Market Reaction 的事件对齐、观察窗口收益和基准差异可复算；不把相关变化宣称为已证明因果。
- [ ] 决策规则和 Decision Trace 可复算；技术面、宏观与市场反应分别可追溯。
- [ ] 信息不足、过期数据、宏观时间不足、分钟行情不可用、虚构引用和 Guard 拒绝能进入明确终态。
- [ ] React 页面可显示市场观点、引用、数据时间、宏观 Actual/Consensus/Surprise、Market Reaction 和失效条件。
- [ ] 小范围 LangGraph 分支与 checkpoint 演示经过验证，不夸大恢复能力。
- [ ] README、启动环境、固定评估、故障记录和 5–8 分钟演示可供面试复现。
- [ ] 首版无订单提交与自动交易路径；后续阶段以独立计划推进。

D16–D18 的持久化、增量索引、最小结构化财务查询和 Financial / Knowledge evidence 组合核心链路已经完成。D21 的统一行情契约和离线 Fixture 验收已经完成。D22 的 Longbridge 适配器、离线测试及 NVDA / AMD 真实在线验收已经完成；D19、D20 延后处理。D13 的历史清单和无匹配资料原因仍保留为遗留项。D14 的附件范围限制为 6-K / 6-K/A 的 HTML EX-99，其他附件不声称覆盖。D17 当前不声称覆盖完整 SEC 历史、并发生产构建锁或独立 freshness 监控。已有代码与记录继续保留，未验收项仍需追踪。
