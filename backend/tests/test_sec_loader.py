from datetime import date, datetime

import pytest

from stock_agent.documents import sec_loader, sec_provider
from stock_agent.documents.schemas import FilingFile, FilingMetadata


@pytest.fixture
def filing():
    return FilingMetadata(
        company_id="NVDA",
        cik="0001045810",
        form="10-Q",
        filing_date=date(2026, 8, 27),
        report_date=date(2026, 7, 26),
        accepted_at=datetime.fromisoformat("2026-08-26T16:20:00-04:00"),
        accession_number="0001045810-26-000075",
        primary_document="nvda-20260726.htm",
        document_url=(
            "https://www.sec.gov/Archives/edgar/data/1045810/"
            "000104581026000075/nvda-20260726.htm"
        ),
    )


@pytest.fixture
def filing_html():
    return """\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
  <head><title>NVIDIA filing</title><style>.hidden { display: none; }</style></head>
  <body>
    <ix:header>inline XBRL metadata</ix:header>
    <script>unsafe script</script><noscript>fallback noise</noscript>
    <h1>Item 1. Business</h1>
    <p>Revenue&nbsp;discussion</p>
    <table>
      <tr><th>USD in millions</th><th>2026</th></tr>
      <tr><td>Revenue</td><td><ix:nonFraction>$100</ix:nonFraction></td></tr>
    </table>
    <table>
      <tr>
        <td>Outer <table><tr><td>Inner</td></tr></table></td>
        <td>Value</td>
      </tr>
    </table>
    <h2>Item 1A. Risk Factors</h2>
  </body>
</html>
"""


@pytest.fixture
def filing_file(filing):
    return FilingFile(
        sequence="1",
        document_name=filing.primary_document,
        document_type=filing.form,
        description="Quarterly report",
        document_url=filing.document_url,
        is_primary=True,
    )


def extract_text(html):
    root = sec_loader.parse_source_html(html)
    content, _ = sec_loader.build_filing_blocks(
        "document",
        sec_loader.extract_source_blocks(root),
    )
    return content


def test_extracts_headings_table_units_and_removes_noise(filing_html):
    content = extract_text(filing_html)

    assert "Item 1. Business" in content
    assert "Item 1A. Risk Factors" in content
    assert "Revenue discussion" in content
    assert "USD in millions | 2026" in content
    assert "Revenue | $100" in content
    assert "inline XBRL metadata" not in content
    assert "unsafe script" not in content
    assert "fallback noise" not in content


def test_nested_table_content_is_not_duplicated(filing_html):
    content = extract_text(filing_html)

    assert content.count("Inner") == 1
    assert "Outer Inner | Value" in content


def test_load_filing_document_keeps_metadata_and_hash(
    filing,
    filing_file,
    filing_html,
    monkeypatch,
):
    monkeypatch.setattr(
        sec_loader,
        "download_filing_html",
        lambda filing: filing_html,
    )

    document = sec_loader.load_filing_document(filing, filing_file)

    assert document.document_id == (
        "sec:0001045810:0001045810-26-000075:nvda-20260726.htm"
    )
    assert document.company_id == filing.company_id
    assert document.report_date == filing.report_date
    assert document.accepted_at == filing.accepted_at
    assert document.document_name == filing_file.document_name
    assert document.document_type == filing_file.document_type
    assert document.is_primary is True
    assert document.source_url == filing_file.document_url
    assert document.content_hash == sec_loader.build_content_hash(document.content)
    assert document.blocks
    assert document.content.count("Inner") == 1
    for index, block in enumerate(document.blocks):
        assert block.block_id == f"{document.document_id}:block:{index}"
        assert block.document_id == document.document_id
        assert document.content[block.start_char:block.end_char] == block.text
        assert block.source_xpath.startswith("/")


def test_attachment_document_uses_its_own_source_url(
    filing,
    filing_file,
    filing_html,
    monkeypatch,
):
    attachment = filing_file.model_copy(
        update={
            "document_name": "exhibit991.htm",
            "document_type": "EX-99.1",
            "document_url": "https://example.com/exhibit991.htm",
            "is_primary": False,
        }
    )
    monkeypatch.setattr(
        sec_loader,
        "download_filing_html",
        lambda filing_file: filing_html,
    )

    document = sec_loader.load_filing_document(filing, attachment)

    assert document.source_url == attachment.document_url
    assert document.document_name == attachment.document_name
    assert document.document_type == attachment.document_type
    assert document.is_primary is False


def test_source_blocks_preserve_text_around_nested_and_ignored_elements():
    html = """
    <html><body>
      <div>Lead<p>Paragraph</p>Tail</div>
      <p>Before<script>noise</script> After</p>
    </body></html>
    """

    root = sec_loader.parse_source_html(html)
    source_blocks = sec_loader.extract_source_blocks(root)
    content, blocks = sec_loader.build_filing_blocks("document", source_blocks)

    assert content == "Lead\n\nParagraph\n\nTail\n\nBefore After"
    assert [block.text for block in blocks] == [
        "Lead",
        "Paragraph",
        "Tail",
        "Before After",
    ]
    assert all(content[block.start_char:block.end_char] == block.text for block in blocks)


def test_unsupported_format_is_rejected_before_download(
    filing,
    filing_file,
    monkeypatch,
):
    unsupported = filing_file.model_copy(
        update={"document_name": "scan.pdf"}
    )
    called = False

    def download(filing):
        nonlocal called
        called = True

    monkeypatch.setattr(sec_loader, "download_filing_html", download)

    with pytest.raises(sec_loader.FilingLoadError) as caught:
        sec_loader.load_filing_document(filing, unsupported)

    assert caught.value.code == "unsupported_format"
    assert called is False


def test_empty_parsed_document_is_rejected(filing, filing_file, monkeypatch):
    monkeypatch.setattr(
        sec_loader,
        "download_filing_html",
        lambda filing: "<html><body><script>noise</script></body></html>",
    )

    with pytest.raises(sec_loader.FilingLoadError) as caught:
        sec_loader.load_filing_document(filing, filing_file)

    assert caught.value.code == "empty_content"


def test_get_filing_files_builds_index_and_document_urls(filing, monkeypatch):
    index_html = """
    <table class="tableFile">
      <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th></tr>
      <tr><td>1</td><td>Quarterly report</td><td><a>nvda-20260726.htm</a></td><td>10-Q</td></tr>
      <tr><td>2</td><td>Press release</td><td><a>exhibit991.htm</a></td><td>EX-99.1</td></tr>
    </table>
    """
    requested = []

    class Response:
        text = index_html

        def raise_for_status(self):
            return None

    def get(url):
        requested.append(url)
        return Response()

    monkeypatch.setattr(sec_provider, "get_sec", get)

    files = sec_loader.get_filing_files(filing)

    archive = (
        "https://www.sec.gov/Archives/edgar/data/1045810/"
        "000104581026000075/"
    )
    assert requested[0] == archive + "0001045810-26-000075-index.html"
    assert [file.document_url for file in files] == [
        archive + "nvda-20260726.htm",
        archive + "exhibit991.htm",
    ]
    assert files[0].is_primary is True
    assert files[1].is_primary is False


def test_selects_ex99_html_for_6k_only(filing):
    foreign_filing = filing.model_copy(
        update={
            "form": "6-K",
            "primary_document": "report.htm",
        }
    )
    files = [
        FilingFile(
            document_name="report.htm",
            document_type="6-K",
            document_url="https://example.com/report.htm",
            is_primary=True,
        ),
        FilingFile(
            document_name="exhibit991.htm",
            document_type="EX-99.1",
            document_url="https://example.com/exhibit991.htm",
            is_primary=False,
        ),
        FilingFile(
            document_name="data.xml",
            document_type="EX-99.2",
            document_url="https://example.com/data.xml",
            is_primary=False,
        ),
    ]

    selected = sec_loader.select_relevant_filing_files(foreign_filing, files)
    assert [file.document_name for file in selected] == [
        "report.htm",
        "exhibit991.htm",
    ]
    assert sec_loader.select_relevant_filing_files(filing, files) == [files[0]]
