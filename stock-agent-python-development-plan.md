# AI 辅助美股研究与仓位风险 Agent · Python 开发计划

- 版本：v3.2，2026-09-18；保留任意美股 ticker 的按需索引，明确 Technical Analysis Engine 与 Decision Engine 的衔接。
- 定位：面向 Agent 开发岗位的可演示项目；模型负责理解问题、调用只读工具、检索资料和解释结果，行情计算、决策规则与仓位风险检查由可复现的 Python 模块完成。
- 排期：面试版 10 周、50 个开发日、约 200 小时；按每天 4 小时、每周 5 天估算。若 Python 异步、数据源接入或部署比预期慢，另留 1–2 周缓冲。
- 当前进度：D11 本地 RAG 基础链路及 D12 通用 Knowledge Tool 接入已完成，见 docs/day12.md；中文检索仍有失败案例。D13 已实现 SEC ticker / CIK、recent filing 发现、外国发行人表单及 as_of 筛选，历史清单与无匹配资料的具体原因遗留，见 docs/day13.md。D14 已实现 SEC HTML 主文档、6-K HTML EX-99 附件选择、正文和表格清洗、来源元数据与内容哈希；原文定位遗留，不标记全部完成，见 docs/day14.md。下一步 D15 最小按需索引。D08/D09 的完成与遗留项见对应文档，早期未验收项继续保留。

本文是拟开发计划。目录、接口和演示能力只有在代码实现并验收后才算完成；不能把 fixture、历史数据或延迟数据标成实时行情。

## 1. 首版目标与边界

首版支持用户询问任意美股公司的 ticker，无需提前把该公司加入白名单或准备资料。系统按问题选择行情、结构化财务、新闻或公司文档；公司文档不存在于本地时按需获取并索引，已有索引可复用并增量更新。用户给出投资期限和仓位后，再结合最新可获得的报价、近几日走势、已发布的 CPI/PPI、近期重大事件以及公司资料，给出有依据的条件性研究判断和仓位风险分析。一般公司研究不要求先填写仓位。

一次完整结果应包含：数据截至时间、资料来源、事实与推断、市场判断、当前仓位风险、假设调整仓位后的风险、反对理由、失效条件，以及资料不足时的明确停止。模型的文字解释不能覆盖程序计算出的数值或风险否决。

首版不固定支持的公司数量，也不预先为全市场建库。保留一个行情提供方、日线及最新报价、一个结构化财务来源（先使用 SEC XBRL Company Facts）、CPI/PPI 两类宏观指标、一个近期新闻来源，以及最多 10 项用户手动录入或只读导入的持仓。日线历史需满足 MA50 等指标的窗口要求，默认请求至少 60 个已完成交易日，不能只取近几天。SEC 为公司文档的首个 Document Provider；一次只获取当前问题范围内必要的 filings。少量固定股票和 fixture 仅用于学习与可复现评估，不能成为产品的公司白名单。

“任意 ticker”指可以提交未预置的美股公司代码，并动态解析和查询；数据可用性由各提供方实际覆盖决定。无效代码、无法匹配发行人、无可用 filing 或供应商缺少数据时，分别返回明确的缺失原因。不能因本地没有索引就拒绝该公司，也不能用其他公司的数据补齐。美股上市的外国发行人需考虑 20-F、40-F、6-K 等资料，不能只找 10-K/10-Q。首版按单用户本地演示设计，不把组合数据接口直接公开到互联网；多用户身份、授权和账户隔离需另行实现与验收。

首版没有订单提交、自动交易、PaperBroker、券商写权限或收益承诺。回测、模拟成交、订单状态机、券商接入和完整自动交易工程进入第二阶段。仓位“假设买入”只计算情景风险，不产生订单。

### 1.1 各类信息走不同路径

| 信息 | 获取方式 | 主要校验 |
| --- | --- | --- |
| 报价、日线历史 | 市场数据提供方的结构化接口 | 交易所覆盖、事件时间、接收时间、是否延迟、窗口长度、缺 K 线与复权口径 |
| 技术指标与关键价位 | Technical Analysis Engine → 确定性计算 TechnicalContext | 已完成 K 线、计算窗口、确认时间、计算版本、候选价位依据与缺失指标 |
| 营收、利润等精确财务指标 | Financial Tool → 结构化财务提供方，先接 SEC Company Facts | 指标口径、币种和单位、报告期、累计与单季口径、filing 及修订版本 |
| CPI/PPI | 官方已发布数据和发布日程 | 统计期、发布时间、修订版本；不能称为实时跳动指标 |
| 业务说明、风险因素、管理层讨论等文档内容 | Knowledge Tool → Document Provider → 按需索引 → 检索 | 公司、filing、报告期、可用时间、版本、证据 ID、原文是否支持结论 |
| 近期新闻 | News/Search Tool → 新闻提供方；先按时间过滤，再取原文 | 关联标的、来源、发布时间、可用时间、冲突与重复内容 |
| 用户现金和持仓 | 手动录入或只读快照 | 币种、数量、成本、快照时间、是否覆盖全部相关账户 |

RAG 用于非结构化资料和可追溯引用；报价、K 线、精确财务指标、CPI/PPI 和仓位金额从结构化接口读取，不让模型从文章中猜精确数字。Market Tool、Financial Tool、Knowledge Tool 和 News/Search Tool 分别提供独立来源，模型按问题组合调用。近期地缘事件由模型提取可核对的事实与潜在影响，最终风险处理仍遵守显式规则；不把一个标题直接映射成 BUY 或 SELL。

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

索引按需建立，首次询问未预置公司时允许产生下载与索引开销；再次查询检查 filing 清单后复用现有索引。初始文档范围明确限制为截至 as_of 最近的年报、最近的可用中期报告及问题需要的近期披露，记录实际覆盖范围；历史问题按所问报告期选择资料，不只查当前最新文件。6-K 等披露不能一律当作季度财报。

Freshness 以 Provider 返回的可用 filing 清单与本地已索引清单比较，记录检查时间；“最新”指声明的文档范围内截至任务 as_of 的可用版本。新增 accession 才触发新增文档处理；修订文件保留独立版本。未变文档不重复下载、分段或生成向量。Embedding 或分段配置变化时重建受影响索引，失败或只完成部分导入不能被标记为最新可用索引。索引是可重建的本地缓存，原文、版本和引用仍需保留。

### 1.3 Agent、决策和风险的职责

1. LangChain Agent 识别用户意图，调用白名单只读工具，并决定是否需要检索更多证据。
2. Knowledge Tool 内部负责索引检查、必要的获取和更新；检索层返回本次实际提供的文档片段及证据 ID，应用层校验引用归属和资料时间。
3. Technical Analysis Engine 根据已验证的报价和 K 线计算 TechnicalContext；Decision Engine 使用其中的指标、候选价位与固定规则生成市场观点和 Decision Trace。分数只是规则分数；未经校准不能称为获利概率。
4. Python 风险模块比较当前组合与用户指定金额的假设组合。超出用户配置的约束时，即使市场观点偏积极，也可以给出“不宜增加该仓位”。
5. 模型把上述结构化结果解释给用户，不得改变风险结论。投资期限、风险偏好或组合信息缺失时，输出一般研究观点并说明无法给出个人仓位判断。

### 1.4 数据时间与保密边界

每个外部输入至少记录 source、data_mode、event_at 或统计期、published_at（如适用）、received_at 和任务 as_of；所有具体时间带时区。研究只使用截至 as_of 已可获得的信息；历史评估不能把后来发布的新闻、财报修订或模型知识伪装成当时已知。

组合数据只保留分析所需的标的、数量、成本、现金和时间；账户号、券商凭据不进入模型上下文或日志。首版用户风险阈值由用户设置或在演示中明确作为假设，不能把任意默认比例说成适合所有人。

### 1.5 技术分析与决策的衔接

```text
Market Data：Quote + 已完成 Bars
    ↓
Technical Analysis Engine → TechnicalContext
    ↓
MarketContext → Guards → Trend / Momentum / Level Factors
    ↓
DecisionResult：市场观点、关键价位、反对理由、失效条件、Trace
    ↓
Agent 调用并解释；个人仓位判断另由 Risk Engine 检查
```

首版以日线技术结构为主：5 / 20 日变化、MA5 / MA20 / MA50、ATR14、成交量变化、已确认 swing high / low，以及由这些高低点产生的 support / resistance candidates。候选价位保留产生它的 K 线和规则，不能称为必然有效的支撑或阻力。参考价格标明来自最新报价还是最近完成日线收盘，及其对应时间；日线结果不能冒充分钟级盘中结构。

用户给出“221.8 怎么看”这样的价格时，先识别标的并区分该价格是用户指定的情景价还是有来源和时间的实际报价；情景价可用于计算距离，但不能冒充当前市场价格。支撑 / 压力和失效条件由程序产生，模型只解释其依据和适用周期。

计算约定在 D23 固定并记录版本：收益变化按完成日线收盘计算，均线使用简单移动平均，ATR14 使用 Wilder 平滑并固定初始化方式，成交量与此前 20 个完成交易日均量比较。swing 初版使用左右各两根完成日线确认，固定同价处理规则；确认时间为右侧第二根 K 线完成时刻，历史 as_of 之前未确认的拐点不能使用。按最近已确认高低点比较 higher high / higher low 等结构，无法确认时明确缺失。支撑 / 阻力候选按参考价上下的位置选择，并记录价格距离和 ATR 距离；距离不等于突破概率。

所有指标使用一致的 OHLC 复权口径，并记录成交量调整方式。与当前报价比较的价位需处于可比价格尺度；缺窗口、缺交易日或拆股口径不一致时标记受影响指标不可用，不让模型补数值。

VWAP 在提供方有合适分钟数据后再增加，必须声明交易时段、session 起止和覆盖完整性。若用分钟 OHLCV 近似计算，明确公式与近似属性；仅有日线时标为不支持，不推算盘中 VWAP。Gap 可后续用一致口径的开盘 / 前收盘数据扩展；Volume Profile 和更复杂市场结构暂不纳入首版必做，不增加开发周数。

## 2. 技术栈与运行方式

| 层 | 首版选择 | 职责 |
| --- | --- | --- |
| 前端 | React + TypeScript | 输入问题与风险假设，展示证据、数据时间、Decision Trace 和风险对比 |
| API | FastAPI + Pydantic | 请求校验、只读任务接口、情景分析、错误与结果契约 |
| Agent | LangChain Python | 模型、工具、结构化输出、调用预算和事件记录 |
| 工作流 | 小范围 LangGraph | 取数、检索、校验、决策、解释的条件分支和一次 checkpoint 演示 |
| RAG | Document Provider + 按需索引 + 关键词 / Embedding / pgvector | 动态发行人解析、索引复用与增量更新、元数据过滤、引用定位和固定评估 |
| 数据 | 一个行情适配器、SEC 文档及 Company Facts、BLS 数据接口、一个近期新闻来源 | 各工具独立取数，统一标的、来源、数据模式和时间字段 |
| 技术分析 | Python 确定性计算 | 收益、均线、ATR、成交量、确认拐点、候选关键价位与 TechnicalContext |
| 决策与风险 | Python 纯函数 / 显式规则 | 使用 TechnicalContext 的因子、市场观点、失效条件、仓位集中度和假设买入风险 |
| 存储 | PostgreSQL + SQLAlchemy；向量阶段使用 pgvector | 发行人映射、filing / 索引状态、原文和片段版本、向量、研究结果、评估和组合快照；按阶段引入 |
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
| 第 5 周 | D21–D25 | 最新报价、日线历史、TechnicalContext、CPI/PPI 与时间校验 | 指标与候选关键价位可复核，数据时间、延迟和统计期清楚可见 |
| 第 6 周 | D26–D30 | 近期新闻与事件风险 | 有来源的事件摘要；失效或冲突资料不产生确定判断 |
| 第 7 周 | D31–D35 | Trend / Momentum / Level 因子、Decision Trace 与市场观点 | 相同快照产生相同观点，关键价位、反对理由与失效条件可追踪 |
| 第 8 周 | D36–D40 | 用户组合快照、风险约束与假设买入 | 同一市场观点对空仓和重仓用户给出不同风险结论 |
| 第 9 周 | D41–D45 | 小范围 LangGraph 与 React 工作台 | 一条完整网页链路和一次条件分支 / checkpoint 演示 |
| 第 10 周 | D46–D50 | 集成评估、故障演示、部署与面试讲解 | 可从干净环境启动的面试版 |

前端任务已提取为独立并行开发线，详见 `docs/frontend-development-plan.md`。当前可在 D08/D09 期间基于公开 API 契约与 mock 完成 FE01/FE02；真实 API 联调在 D10 收口，后期引用、数据时间、Decision Trace 与风险界面继续受对应后端契约约束。

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

D04/D05 的未验收项继续按对应文档追踪，不因进入 RAG 阶段而标为完成。D04 的 ResearchOutput 和 EvidenceClaim 是研究回答模型；后面新增市场、组合与风险模型，不要求现在把所有领域对象塞进一个 schema。

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
| D14 | 下载必要 filing，解析与清洗正文，并保留引用上下文 | SEC HTML 主文档、6-K HTML EX-99 附件选择、标题与表格文字清洗、嵌套表格、来源元数据、接受时间、版本身份、内容 hash、不支持格式和空正文已实现并验证；其他附件范围明确不覆盖，原文定位遗留，不标记全部完成，见 docs/day14.md |
| D15 | 实现 ensure_company_index：首次查询不存在索引时才获取、分段和嵌入 | 首次查询一个未预置公司可建立索引并返回片段；重复调用不产生重复文档。文档身份、解析 / 分段 / Embedding 配置可追踪；阶段内先用本地索引状态，D16 完成跨进程持久化 |

周门槛：Day12 的 Agent 接口保持不变，Day15 可在内部切换到真实 Provider；未预置公司无需新增工具或修改公司列表。用户可回到证据原文；“命中一个 ID”和“句子受证据支持”分开检查。

SEC 接入通过后端完成，按官方要求声明 User-Agent 并遵守访问频率限制；只获取所需资料，不批量扫描全市场。Submissions、XBRL 与访问约束见 [SEC API 文档](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)和 [EDGAR 访问说明](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)。

### 第 4 周：持久化索引、增量更新与评估

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D16 | 将原文、filing 清单、索引状态、片段与向量存入 PostgreSQL / pgvector | 重启后能检索已有公司，未变文档不重复嵌入；按发行人、可用时间和文档版本过滤。索引配置含模型、revision、维度和分段版本，引用可回到保存的原文 |
| D17 | 实现 Freshness 检查和新增 filing / 修订的增量更新 | 无新增时复用；模拟新增 filing 时只处理新增文档；修订不覆盖历史证据。任务 as_of 之后的文档不能参与检索，获取或索引失败不能声称索引已最新 |
| D18 | 明确 Market / Financial / Knowledge / News Tool 独立边界；接入最小结构化财务查询 | SEC Company Facts 先提供少量精确指标，保留单位、报告期和 filing 来源；Agent 能组合财务指标与文档证据。行情先复用现有 fixture，真实行情在 D21–D25 接入，真实新闻在 D26–D30 接入，未接入能力明确标记 |
| D19 | 建关键词基线，准备开发集 / 保留集及必需证据标注 | 关键词与向量使用同一资料版本和过滤条件；案例覆盖公司、中文问题、报告期、冷启动、复用、增量与无资料；实现一个简单混合检索对照 |
| D20 | 计算 Recall@k、引用可访问率，并人工复核事实支持 | 对关键词、向量和混合结果给出原始计数与失败分析；检查精确指标的口径。记录首次索引与复用耗时，不捏造检索提升或全市场覆盖比例 |

周门槛：使用一个未预置公司展示首次索引、重启后的复用，再用固定新增 filing 样例展示增量更新。持久化复用不会省略 freshness 检查；检索能运行不代表全部问题都能回答。

### 第 5 周：行情、技术分析与宏观

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D21 | 定义 MarketDataProvider、Quote 和 Bar 契约，支持动态 ticker | fixture、historical、live 模式与延迟属性分别记录；明确周期、交易时段、K 线完成状态和复权口径；证券 ticker 与发行人 CIK 分开，上层不依赖供应商字段 |
| D22 | 接入一个提供方的最新报价和至少 60 个已完成交易日的日线历史 | 未预置 ticker 无需改代码即可查询；保存市场事件时间和本地接收时间，识别休市、延迟、历史不足与供应商未覆盖标的；分钟数据按供应商能力后续接入 |
| D23 | 实现最小 Technical Analysis Engine 与 TechnicalContext | 计算 5 / 20 日变化、MA5 / MA20 / MA50、ATR14、成交量变化、已确认 swing high / low 与支撑 / 阻力候选；固定窗口、初始化、同价和价位选择规则，用固定 OHLCV 样例复核；不使用未完成或截至 as_of 尚未确认的 K 线，不从模型文本提取价格；VWAP 有合适分钟数据后再增加 |
| D24 | 接入 BLS 已发布 CPI/PPI 与发布日期 | 统计期和发布时间分开；缺少预期值时不声称“超预期” |
| D25 | 建数据新鲜度和技术指标缺失检查 | 过期报价、缺 K 线、窗口不足、复权口径冲突或未来时间资料会使受影响指标不可用，降低结论级别或停止个人判断；未覆盖分钟数据时不声称有 VWAP |

首版不为“实时”购买特定数据套餐做假设；实际 feed、交易所覆盖和延迟能力按选定供应商核对并记录。

### 第 6 周：新闻与事件

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D26 | 选一个可用的近期新闻来源和独立 News/Search Tool | 按动态 ticker / 公司身份检索；保存原文链接、发布时间、获取时间、来源和关联标的 |
| D27 | 按时间和相关性过滤、去重近期新闻 | 旧闻、重复转载和未来发布内容不冒充当前事件 |
| D28 | 用模型提取事件事实、涉及对象和不确定性 | 结构化输出有来源；模型不能自行编造事件或发布时间 |
| D29 | 建有限的事件风险规则，例如事件未确认时降低确定性 | 地缘标题不能自动转为方向性买卖信号 |
| D30 | 用离线事件集和少量真实样例验证 | 冲突来源、错误标的、失效链接和无相关新闻有明确结果 |

近期新闻检索不必从一开始就全部做 Embedding。结构化宏观发布与近期新闻时间过滤是两种不同问题；财报 RAG 仍作为面试主展示能力。

### 第 7 周：可复现的市场判断

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D31 | 定义包含 TechnicalContext 的 MarketContext、FactorOpinion 与 DecisionResult | 输入包含报价 / 日线版本、指标窗口、计算版本和 as_of；输出包含市场观点、关键价位、反对理由、失效条件、规则版本和证据 |
| D32 | 实现 TrendFactor、MomentumFactor、LevelFactor 三个简单因子 | Trend 使用参考价与 MA20 / MA50；Momentum 使用近期变化与已确认高低点结构；Level 使用参考价距支撑 / 阻力候选的价格及 ATR 距离；复用 D23 结果，不重复计算指标。固定阈值与合并规则，避免相近信号重复加分；相同快照和规则版本输出一致 |
| D33 | 实现 Guard → Factors → Decision 的纯函数流程 | 缺数据或冲突数据可返回 insufficient_information / wait |
| D34 | 生成 Decision Trace、反对理由和判断失效条件 | 能指出每个因子值、阈值、候选价位依据和最终判断由哪条规则产生；突破 / 跌破条件明确使用何种周期、价格和确认方式，不能把盘中触及描述为收盘确认 |
| D35 | 与 LangChain Agent 整合并演示价格 / 结构问题 | 对“当前价格怎么看、支撑压力在哪里、什么条件下判断失效”返回带数据时间和规则依据的条件性解释；Agent 只能调用和解释决策结果，不能改数值、编造价位或覆盖 Guard |

首版的“置信分数”仅为事先定义的规则分数，不能表述为涨跌概率或胜率。没有充分验证的情况下，使用偏积极、中性、偏谨慎和信息不足等可解释状态。

### 第 8 周：用户仓位与风险

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D36 | 定义 PortfolioSnapshot：现金、币种、持仓数量、成本和 as_of | 手动录入或只读导入；拒绝负数量、币种不明和过期快照 |
| D37 | 定义 RiskProfile：期限、风险承受范围和用户设置的约束 | 不替用户猜测可承受损失；缺字段时说明个人判断受限 |
| D38 | 计算当前组合市值、单股集中度和现金占比；有可靠行业映射时再算行业集中度 | 金额使用 Decimal；缺报价或行业映射时标明无法计算，不给出伪精确数字 |
| D39 | 用用户指定的假设金额比较调整前后仓位 | 输出当前占比、假设后占比、触发的规则；不创建订单 |
| D40 | 验证空仓、重仓、缺报价、过期组合与币种不一致案例 | 市场观点与个人风险结论分别呈现；风险否决不能被模型改写 |

仓位风险是首版必做，但不接券商交易权限。若手动录入的组合不完整，结果必须标明覆盖范围和局限。

### 第 9 周：小范围工作流与界面

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D41 | 建 LangGraph 状态和取数、检索、校验、决策、解释节点 | 证据不足最多补查一次，随后明确结束 |
| D42 | 加一个 checkpoint 与取消 / 恢复演示 | 能指出哪些节点会重跑；不会误称已完成多 worker 容灾 |
| D43 | 完善 React 对话输入和结构化结果页面 | 接受未预置 ticker；首次资料获取 / 索引期间显示任务进度，显示行情时间、宏观统计期、引用和不确定性 |
| D44 | 展示 TechnicalContext、关键价位、Decision Trace、当前仓位与假设后风险 | 显示分析周期、参考价时间、候选价位依据与失效条件；市场观点和个人风险结论在界面上清楚分开 |
| D45 | 演示正常、资料不足、风险否决及取消路径 | 旧任务结果不会覆盖当前页面；状态与最终结果一致 |

如果增加 SSE，持久事件与临时 token 分开处理；断线后读取快照，不把不完整文本当成最终对象。

### 第 10 周：评估、部署和表达

| 开发日 | 任务 | 完成标准 |
| --- | --- | --- |
| D46 | 固定模型、提示、资料、行情、规则和风险配置版本 | 相同离线案例可复现；真实接口案例明确标记 |
| D47 | 汇总 Agent / RAG 指标和人工支持性复核 | 工具选择、证据命中、引用支持、缺资料处理各自有结果 |
| D48 | 汇总时间、索引与组合风险故障案例 | 无效 ticker、无 filing、索引未完成、未来资料、过期报价、缺组合、重仓和币种错误不会被悄悄忽略 |
| D49 | 按 README 从干净环境启动；整理部署和密钥配置 | 示例不暴露凭据，功能边界和数据来源清楚 |
| D50 | 完成 5–8 分钟演示、架构图和模拟面试问答 | 能现场走完 Agent → RAG / 数据工具 → 决策 → 组合风险 → 解释 |

第 10 周原则上不新增业务功能。展示中至少有一个“市场观点偏积极，但用户现有仓位过高，因此不建议增加仓位”的可复现案例。

## 5. 接口、领域模型与数据

### 5.1 首版接口草案

| 方法与路径 | 用途 | 关键检查 |
| --- | --- | --- |
| POST /api/chat/runs | 从自然语言创建对话式研究 | 消息校验、标的识别、服务端 as_of/data_mode、信息不足路径 |
| POST /api/runs | 创建已归一化的研究与风险分析 | 问题、标的、资料截止时间、身份和预算；保留现有教学与评估契约 |
| GET /api/runs/{run_id} | 读取结果快照 | 任务身份、最新状态和版本 |
| GET /api/runs/{run_id}/events | 可选事件订阅 | run_id、seq、断线后快照重建 |
| POST /api/portfolio-snapshots | 手动保存组合快照 | 数量、币种、时间、数据最小化 |
| POST /api/portfolio-scenarios | 计算假设买入后的风险 | 用户指定金额、快照版本、价格时间；无外部动作 |
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
| search_news(company_id, question) | 近期事件原文、来源与时间 | D26–D30 接真实新闻来源 |

工具命名不带特定公司。公司解析、按需索引和 freshness 属于工具内部实现；任务 as_of、data_mode 由应用层的请求上下文传入，不能由模型绕过。fixture 工具仍可限定教学资料，但真实 Provider 不能沿用只允许 NVDA 的判断。宏观文档与公司 filings 分开标识，不伪造所属公司；当前 None 宏观过滤保留为本地练习。

### 5.2 关键领域对象

| 对象 | 必要内容 | 主要业务校验 |
| --- | --- | --- |
| ResearchOutput | status、facts、inferences、missing_information、data_mode | 本次证据 ID、资料模式与事实支持 |
| CompanyIdentity | 查询 ticker、规范 ticker、发行人 CIK、公司名、来源 | 未预置代码可解析；不同股类可共享发行人文档，报价仍分别查询 |
| FilingDocument | CIK、accession、form、主文档及必要附件、报告期、接受 / 可用时间、来源、版本与 hash | 获取范围与任务匹配；修订和原文独立可追踪，文档位置可回查 |
| CompanyIndexState | 发行人、已索引文档版本、索引配置、覆盖范围、检查时间与完成状态 | 配置匹配才复用；未完成的索引不冒充最新；未来 filing 不进入历史研究 |
| Quote / Bar | 标的、价格或 OHLCV、币种、event_at、received_at、source、feed | 数据时效、交易时段、完整 K 线 |
| TechnicalContext | 标的、as_of、分析周期、参考价格及时间、行情版本、复权口径、指标及窗口、确认拐点、候选支撑 / 阻力、缺失项、计算版本 | 完成 K 线与确认时间符合截止要求；窗口足够；关键价位有原始 K 线依据；日线与分钟数据能力明确区分 |
| MarketContext | Quote / Bars、TechnicalContext、相关财务 / 宏观 / 事件证据、数据版本和 as_of | 技术计算与决策使用同一行情快照；各类来源保持独立，缺失项由 Guard 判断 |
| FinancialMetric | 指标、taxonomy / concept、数值、单位、币种、报告期、filing、来源和可用时间 | 年度、单季与累计口径不混用；缺少对应指标时明确缺失 |
| MacroObservation | 指标、统计期、数值、published_at、source | 只使用已发布版本；修订可追踪 |
| NewsEvidence | 标题、原文、标的、published_at、received_at、source | 时间过滤、去重、可访问性与支持关系 |
| DecisionResult | market_view、factors、guards、关键价位、反对理由、失效条件、trace、rule_version | 规则可复现；缺数据不强行输出方向；关键价位与 TechnicalContext 一致 |
| PortfolioSnapshot | cash、currency、positions、as_of、coverage | 数量和金额有效，持仓覆盖范围明确 |
| RiskProfile | horizon、用户给定的风险约束、版本 | 无用户授权不擅自设为普适阈值 |
| RiskAssessment | 当前占比、情景后占比、触发规则、结论 | 使用同一报价时间和组合版本计算 |
| RecommendationResult | 市场观点、个人风险结论、事实、推断、来源、条件与缺失信息 | 风险否决优先；模型不得改写结构化结果 |

研究模型和用户组合模型分开。Pydantic 校验字段和类型；应用层继续检查证据归属、资料发布时间、报价新鲜度、组合覆盖范围和用户约束。金额采用 Decimal / 数据库 NUMERIC，并固定前后端序列化方式。

### 5.3 目录与持久化

| 路径 | 职责 |
| --- | --- |
| backend/src/stock_agent/agents/ | LangChain Agent 与 Manual Agent 对照 |
| backend/src/stock_agent/tools/ | 白名单只读工具和注册表 |
| backend/src/stock_agent/retrieval/ | 复用 D11 代码；Document Provider、按需索引、分段、持久化检索和引用，不再新建平行 knowledge 包 |
| backend/src/stock_agent/market_data/ | 报价、日线、时间和来源适配 |
| backend/src/stock_agent/technical/ | D23 确定性指标、确认拐点、关键价位候选与 TechnicalContext；按需创建 |
| backend/src/stock_agent/financial_data/ | SEC Company Facts 结构化财务指标与口径归一化 |
| backend/src/stock_agent/macro/ | CPI/PPI 发布数据 |
| backend/src/stock_agent/news/ | 近期新闻检索与事件提取 |
| backend/src/stock_agent/decision/ | 因子、Guard 和 Decision Trace |
| backend/src/stock_agent/portfolio/ | 组合快照与假设情景 |
| backend/src/stock_agent/risk/ | 用户约束、仓位计算和风险结论 |
| backend/src/stock_agent/workflows/ | 小范围 LangGraph 工作流 |
| backend/src/stock_agent/api/ | FastAPI 请求与响应 |
| backend/src/stock_agent/storage/ | 资料、结果、组合和评估持久化 |
| frontend/src/ | React 输入、引用、决策与风险展示 |
| backend/tests/、evals/、docs/ | 确定性测试、固定评估和面试资料 |

目录随开发日逐步创建，不预建空包；Provider 与索引协调逻辑先放在现有 retrieval 模块内，不额外搭建索引服务。存储至少区分 runs / run_results、company_identities / filings / index_states、document_revisions / chunks / embeddings、market_snapshots / financial_metrics / macro_observations / news_evidence、portfolio_snapshots / risk_profiles / risk_assessments。没有订单表或模拟成交表。

SEC 文档用发行人 CIK、accession、文档名和内容版本标识；片段引用另包含分段版本与原文位置。Embedding 配置版本参与向量索引身份；同一份未变文档在同一配置下只嵌入一次，不因不同 ticker 指向同一发行人而重复索引。程序重启后仍可打开历史回答对应的证据版本。

HTTP 客户端在合适生命周期内复用；异步数据库 session 按请求或任务隔离。模型日志只保存允许的事件、用量、结果引用和安全错误，不保存密钥、账户号、原始异常或隐藏思维链。

## 6. 评估与验收口径

1. D05 原有 10 个工具与格式案例继续保留。新增案例覆盖检索、引用、行情延迟、宏观发布时间、新闻冲突、仓位缺失、重仓、币种不一致和风险否决。
2. RAG 记录固定 k 下的证据 Recall@k、引用可访问率和人工抽查的句子支持率。关键词、向量、混合路径使用相同问题和资料版本比较。
3. Agent 记录工具选择、参数合法性、调用预算、停止条件、输出结构、模型用量和耗时。Manual Agent 与 LangChain 的对照以行为为准，不以代码行数为准。
4. 决策与风险模块用固定输入做确定性测试；同一快照、规则版本和用户约束必须得到同一结果。模型解释若与结构化风险结论冲突，整体结果不能通过验收。
5. 历史样例只用该时点已发布资料。实时接口样例与离线 fixture 分开标记；无法证明的数据新鲜度不写成实时。没有完整回测时，不报告策略收益率或胜率。
6. 面试报告保留失败案例，不用一组演示问答充当完整评估。样本小就给出原始计数和局限，不捏造提升比例。
7. 任意 ticker 能力必须用未预置公司验收：无需编辑股票列表，首次查询完成按需索引；再次查询和重启后不重复下载或嵌入未变文档。用记录的 Provider 输入计数验证实际复用，不只看响应更快。
8. 固定样例覆盖同一发行人的不同股类、外国发行人适用表单、无效 ticker、无 filing、报告期错误、新增 filing、修订与索引配置变化。只处理应更新文档；更新失败、部分索引和资料不足均有明确结果。
9. 分别验证 Market / Financial / Knowledge / News 工具选择。精确财务数值不能由 RAG 摘要替代，新闻也不能冒充 SEC 披露。首次获取和复用耗时分开记录；离线评估固定 filing 清单，不能让真实 freshness 更新改变资料版本。
10. 技术分析使用固定 OHLCV 样例复核收益、均线、ATR 初始化、成交量窗口、拐点确认、价位选择和距离；覆盖历史不足、缺交易日、拆股口径、同价拐点、未完成 K 线与未来确认时间。分钟覆盖不足时不输出 VWAP；Agent 的价位和失效条件必须与 TechnicalContext / DecisionResult 一致。

## 7. 后续阶段：模拟与自动交易

首版交付后，再单独规划 PaperBroker、历史回放与费用 / 成交假设、券商模拟账户、订单意图与状态机、额度预留、幂等、对账、恢复和停用开关。先验证只读账户与持仓，再决定是否接入模拟下单；真实交易权限是更后的独立决策，不由面试版通过自动推导。

自动交易阶段必须区分“发起请求”“券商受理”“部分成交”“撤单请求”和“撤单已确认”。提交超时不代表订单未发生；重试前需查询和对账。历史回测还需处理数据可用时间、复权、交易日历、费用、滑点和未来数据穿越。没有足够证据时不设定固定完成日期或宣称收益。

## 8. 面试演示与讲解重点

演示顺序：输入一个本地无索引的美股公司 ticker → LangChain Agent 调用通用 Knowledge Tool → Provider 获取必要资料并首次索引 → 展示可打开的原文证据 → 重复查询 / 重启后复用索引 → 用固定新增 filing 样例展示增量更新。再结合行情 / 结构化财务 / CPI / 新闻及用户仓位，展示决策追踪、假设后风险和解释；保留一个过期行情、虚构引用或高集中度的失败分支。

准备说明：

- 手写工具循环与 LangChain 的边界：框架做了什么，白名单、预算与业务校验仍由谁负责。
- RAG 的关键词基线、向量 / 混合检索、过滤顺序和支持性评估。
- 为什么不用全市场预建库；Document Provider、ensure_company_index、持久化缓存与增量更新分别做什么，首次查询成本与复用如何验证。
- ticker 与发行人 CIK 的区别；为什么 SEC 文档检索、结构化财务、行情与新闻要走不同工具。
- LangGraph checkpoint 与业务结果存储的区别，以及首版没有实现的多 worker 恢复。
- 为什么报价、宏观数值和仓位计算不交给模型猜；为什么新闻只能在有来源、有时间的条件下参与判断。
- 为什么市场观点与用户组合风险可能相反；规则分数不能直接称为收益概率。
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
| 宏观发布 | [BLS 数据 API](https://www.bls.gov/developers/)、[CPI 日程](https://www.bls.gov/schedule/news_release/cpi.htm)、[PPI 日程](https://www.bls.gov/schedule/news_release/ppi.htm) |
| 用户风险背景 | [Investor.gov 资产配置](https://www.investor.gov/introduction-investing/getting-started/asset-allocation)、[FINRA 集中度风险](https://www.finra.org/investors/insights/concentration-risk) |

## 10. 面试版交付清单

- [ ] 现有 D01–D05 有对应真实 / 离线验收记录；未完成任务仍标为未完成。
- [x] Manual Agent 与 LangChain Agent 共用只读工具契约，并有固定案例对照（D08 轻量 runner 与报告已完成）。
- [x] D11 本地 RAG 基础链路跑通，已记录中文检索失败；不代表真实按需索引已完成。
- [x] Day12 通用 Knowledge Tool 接入统一注册表与 Agent，本次引用归属及无资料路径通过验证（见 docs/day12.md）。
- [ ] 未预置 ticker 可动态解析并按需获取资料，无需增加公司白名单。
- [ ] 原文、索引状态和向量持久化；重复查询及重启后复用，新增 filing / 修订增量更新可验证。
- [ ] RAG 有小型资料集、关键词基线、向量 / 混合对照、证据定位与评估报告。
- [ ] Market / Financial / Knowledge / News 工具独立；报价、日线、精确财务、CPI/PPI 和新闻均有来源、时间与数据模式。
- [ ] Technical Analysis Engine 输出可复核的收益、均线、ATR、成交量、确认拐点和候选关键价位；明确分析周期、窗口、时间与缺失项，VWAP 按分钟数据能力提供。
- [ ] 决策规则、Decision Trace、仓位风险及假设买入前后对比可复算。
- [ ] 信息不足、过期数据、冲突新闻、虚构引用和风险否决能进入明确终态。
- [ ] React 页面可显示市场观点、个人风险结论、引用、数据时间和条件。
- [ ] 小范围 LangGraph 分支与 checkpoint 演示经过验证，不夸大恢复能力。
- [ ] README、启动环境、固定评估、故障记录和 5–8 分钟演示可供面试复现。
- [ ] 首版无订单提交与自动交易路径；后续阶段以独立计划推进。

从 D15 的最小按需索引继续推进；D13 的历史清单和无匹配资料原因，以及 D14 的原文定位仍保留为遗留项。D14 附件范围限制为 6-K / 6-K/A 的 HTML EX-99，其他附件不声称覆盖。D01–D14 已有代码与记录保留，未验收项仍需追踪。真实数据工程按 D13–D17 逐步落地，Day12 未提前实现 Provider、持久化缓存或增量更新。50 个开发日的主框架保留，D23 / D32 明确技术分析与因子衔接，不新增开发周；数据覆盖、解析或技术计算工作量超出每日时限时使用原有缓冲，不以减少支持的公司数量代替产品目标。
