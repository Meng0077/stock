# D14：SEC filing 下载与正文解析

2026-09-19：已完成 SEC HTML 主文档下载、6-K HTML EX-99 附件选择、基础正文与表格清洗、来源元数据和内容哈希。嵌套表格不再重复输出，解析与附件行为已有固定自动测试。原文定位按用户要求遗留，因此 Day14 不标记全部完成。

## 当前流程

```text
FilingMetadata
    → 读取 filing 详情页文件表
    → 选择主文档；6-K / 6-K/A 另选 HTML EX-99 附件
    → 逐个检查格式并下载 SEC HTML
    → BeautifulSoup + lxml 解析
    → 删除 script / style / noscript / ix:header
    → 从内到外展开表格
    → 提取正文并规范空白
    → 拒绝空正文
    → 生成 document_id 和 SHA-256 content_hash
    → FilingDocument
```

当前只接受 `.htm` 和 `.html` 文档。所有支持表单选择 primary document；6-K / 6-K/A 另外选择 document type 以 `EX-99` 开头的 HTML 附件。其他附件类型和非 HTML 附件不进入首版范围。PDF、扫描件等显式加载时返回 `unsupported_format`；清洗后没有正文时返回 `empty_content`，不会生成空文档。

FilingFile 保存 sequence、document_name、document_type、description、document_url 和 is_primary。FilingDocument 保留 company_id、CIK、form、filing_date、report_date、accepted_at、accession，并从当前 FilingFile 保存 document_name、document_type、is_primary 和该文件自己的 source_url。document_id 使用 CIK、accession 和文件名组成；content_hash 对规范化后的正文计算，用于识别实际送入后续分段流程的内容版本。

正文保留 HTML body 中的标题文字。表格按行输出，单元格使用 ` | ` 分隔，因此表格中已有的币种和单位文字会继续存在。嵌套表格按从内到外的顺序替换，避免内层行同时被外层递归遍历而重复输出。

## 运行方式

在项目根目录执行自动测试：

```bash
backend/.venv/bin/python -m pytest -c backend/pyproject.toml
```

SEC 实网验证会下载 NVDA 的最新 10-Q 和 10-K：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python evals/verify_filing_download.py
```

共 278 项自动测试通过。Day14 的 7 项固定测试覆盖 XML 声明、标题、段落空白、表格单位、inline XBRL 数字、嵌套表格、噪声删除、元数据传递、内容哈希、不支持格式、空正文、filing 目录 URL、文件 URL、primary 标记，以及 6-K 的 EX-99 HTML 附件选择。SEC 实网验证覆盖 NVDA 10-Q、10-K、重复下载结果稳定、不支持格式和空正文，全部通过。TSM 6-K 的补充实网检查在读取 submissions 时发生 SEC ReadTimeout，因此不记录为已通过；附件选择逻辑由固定样例验证。

## 遗留

1. FilingDocument 当前只有规范化后的整篇正文，没有章节对象、DOM 路径、字符范围与 SEC 原文锚点。Day15 分段前需要确定定位契约，引用暂时只能回到 source_url，不能直接跳到对应原文位置。
2. 附件范围目前明确限制为 6-K / 6-K/A 的 HTML EX-99。其他 exhibit、XBRL 数据文件、PDF 和图片不在首版覆盖范围内，索引状态必须记录这一覆盖范围，不能声称已处理完整 filing。

Day15 可以基于当前 FilingDocument 开始最小按需索引，但完成可回查引用前必须补齐第 1 项。Day15 只索引当前明确选择的文件，不自动扩展附件范围。
