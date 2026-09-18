# D13：SEC Document Provider

2026-09-18：ticker → CIK → recent filing 元数据流程已实现。已补齐外国发行人表单和 as_of 时间筛选；历史清单读取、无匹配资料的具体原因按用户要求遗留，Day13 不标记全部完成。

## 当前流程

```text
company_id + as_of
    → SEC ticker / CIK 映射
    → company submissions 的 filings.recent
    → 表单筛选与元数据构建
    → accepted_at <= as_of
    → 按 accepted_at 倒序，取 limit 条
```

默认支持 10-K、10-Q、20-F、40-F、6-K 及对应 /A 修订表单，也允许通过 forms 选择其中的表单。6-K 保留原始表单标识，不自动当作季度财报；修订文件保留各自的 accession 和主文档。

FilingMetadata 保留公司代码、CIK、form、filing_date、report_date、accepted_at、accession_number、primary_document 和 document_url。accepted_at 对应 SEC acceptanceDateTime，必须包含时区；当前以此作为资料可用时间筛选依据。filing_date 和 report_date 仍是日期，不用于日内截止时间判断。

as_of 是可选参数，省略或传入 None 时使用调用时的当前 UTC 时间；显式传入时必须包含时区。截止时刻本身公开的文件会保留，截止之后的文件被排除；筛选先于排序和 limit，避免后来公开的文件挤占结果。

## 运行方式

在项目根目录调用：

```python
from datetime import datetime, timezone
from stock_agent.documents.sec_provider import get_recent_filings

filings = get_recent_filings(
    company_id="TSM",
    as_of=datetime.now(timezone.utc),
    forms={"20-F", "6-K"},
    limit=3,
)
```

实网验证（只读 SEC 接口）：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python evals/verify_sec_provider.py
```

自动测试：

```bash
backend/.venv/bin/python -m pytest -c backend/pyproject.toml
```

271 项自动测试通过，其中新增 15 项验证默认及指定表单、修订、时区换算、同日截止前后、截止时刻包含关系、筛选后排序和 limit，以及省略 as_of 或传入 None 时使用当前 UTC 时间。

SEC 实网验证：NVDA、AMD、外国发行人 TSM，以及无效 ticker 四项通过。

## 遗留

1. 暂不读取 filings.files 指向的历史清单。历史 as_of 超出 recent 覆盖范围时，当前不能保证资料完整。
2. 无效 ticker 仍抛出 UnknownTickerError；ticker 存在但没有匹配的 filing 时仍返回空列表，暂不区分具体缺失原因。

本阶段只发现元数据，不下载解析正文，也不创建或更新向量索引。相关工作继续留在 Day14–17。
