from copy import deepcopy
from pathlib import Path
import re
from typing import Literal

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

import hashlib

from stock_agent.documents.schemas import FilingFile, FilingMetadata, FilingDocument
from stock_agent.documents.sec_provider import SEC_HEADERS, build_document_url

BLOCK_TAGS = {
    "address",
    "article",
    "blockquote",
    "br",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "p",
    "section",
}

ATTACHMENT_FORMS = {
    "6-K",
    "6-K/A",
}

SUPPORTED_HTML_SUFFIXES = {
    ".htm",
    ".html",
}

class FilingLoadError(ValueError):
    def __init__(
        self,
        code: Literal[
            "unsupported_format",
            "empty_content",
        ],
        filing_file: FilingFile,
    ):
        self.code = code
        self.filing_file = filing_file

        super().__init__(
            f"{code}: {filing_file.document_url}"
        )


def check_supported_format(
    filing_file: FilingFile,
) -> None:
    suffix = Path(
        filing_file.document_name
    ).suffix.lower()
    if suffix not in SUPPORTED_HTML_SUFFIXES:
        raise FilingLoadError('unsupported_format', filing_file)

def check_content( content: str, filing_file: FilingFile,) -> None:
    if not content.strip():
        raise FilingLoadError("empty_content", filing_file)

def download_filing_html(
    filing_file: FilingFile,
) -> str:

    response = httpx.get(
        filing_file.document_url,
        headers=SEC_HEADERS,
        timeout=30.0
    )

    response.raise_for_status()

    return response.text

def parse_filing_html(
    html: str,
) -> BeautifulSoup:
    html = re.sub(
        r"^\s*<\?xml[^>]*\?>",
        "",
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    return BeautifulSoup(html, "lxml")

def remove_obvious_noise(
    soup: BeautifulSoup,
) -> BeautifulSoup:
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    for tag in soup.find_all():
        if tag.name == "ix:header" or (
            tag.name == "header" and tag.prefix == "ix"
        ):
            tag.decompose()
    return soup


def extract_inline_text(
    tag,
) -> str:
    text = "".join(str(value) for value in tag.strings)

    return re.sub(r"\s+", " ", text).strip()

def extract_dom_text(
    root,
) -> str:
    parts = []
    def add_newline():
        if parts and not parts[-1].endswith("\n"):
            parts.append("\n")

    def walk(node):
        if isinstance(node, NavigableString):
            parts.append(str(node))
            return
        if not isinstance(node, Tag):
            return

        is_block = node.name in BLOCK_TAGS

        if is_block:
            add_newline()
        for child in node.children:
            walk(child)

        if is_block:
            add_newline()
    walk(root)

    return "".join(parts)

def extract_table_text(
    table,
) -> str:
    rows = []

    for row in table.find_all("tr"):
        cells = []
        for cell in row.find_all(["th", "td"]):
            text = extract_inline_text(cell)
            if text:
                cells.append(text)
        if cells:
            rows.append(" | ".join(cells))

    return  "\n".join(rows)

def extract_filing_text(
    soup: BeautifulSoup,
) -> str:
    content = deepcopy(soup.body or soup)
    for table in reversed(content.find_all("table")):
        table_text = extract_table_text(table=table)

        table.replace_with(f"\n{table_text}\n")
    return extract_dom_text(content)

def normalize_filing_text(
    text: str,
) -> str:
    text = (
        text
        .replace("\xa0", " ")
        .replace("\u200b", "")
    )

    lines = []

    for raw_line in text.splitlines():
        line = re.sub( r"[ \t]+", " ", raw_line ).strip()

        if line:
            lines.append(line)
        elif lines and lines[-1] != "":
            lines.append("")

    return "\n".join(lines).strip()


def build_document_id(
    filing: FilingMetadata,
    filing_file: FilingFile,
) -> str:
    return (
        f"sec:"
        f"{filing.cik}:"
        f"{filing.accession_number}:"
        f"{filing_file.document_name}"
    )


def build_content_hash(
    content: str,
) -> str:
    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()


def load_filing_document(filing: FilingMetadata, filing_file: FilingFile) -> FilingDocument:
    check_supported_format(filing_file)

    html = download_filing_html(filing_file)

    soup = parse_filing_html(html)
    cleaned_soup = remove_obvious_noise(soup=soup)
    raw_text = extract_filing_text(cleaned_soup)
    content = normalize_filing_text(raw_text)

    check_content(content, filing_file)

    content_hash = build_content_hash(content=content)
    return FilingDocument(
        document_id=build_document_id(filing, filing_file),
        company_id=filing.company_id,
        cik=filing.cik,
        form=filing.form,
        filing_date=filing.filing_date,
        report_date=filing.report_date,
        accepted_at=filing.accepted_at,
        accession_number=filing.accession_number,
        document_name=filing_file.document_name,
        document_type=filing_file.document_type,
        is_primary=filing_file.is_primary,
        source_url=filing_file.document_url,
        content=content,
        content_hash=content_hash,
    )


def get_filing_files(
    filing: FilingMetadata,
) -> list[FilingFile]:
    index_url = build_document_url(
        cik=filing.cik,
        accession_number=filing.accession_number,
        document_name=f"{filing.accession_number}-index.html",
    )
    response = httpx.get(
        index_url,
        headers=SEC_HEADERS,
        timeout=30.0,
    )
    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "lxml",
    )

    files = []

    for table in soup.select("table.tableFile"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            link = cells[2].find("a")

            if link is None:
                continue

            document_name = (
                link.get_text(strip=True)
            )

            if not document_name:
                continue

            sequence = (cells[0].get_text( " ", strip=True,) or None)

            description = (
                cells[1]
                .get_text(
                    " ",
                    strip=True,
                )
                or None
            )

            document_type = (
                cells[3]
                .get_text(
                    " ",
                    strip=True,
                )
            )

            files.append(
                FilingFile(
                    sequence=sequence,
                    document_name=(
                        document_name
                    ),
                    document_type=(
                        document_type
                    ),
                    description=description,
                    document_url=build_document_url(
                        cik=filing.cik,
                        accession_number=filing.accession_number,
                        document_name=document_name,
                    ),
                    is_primary=(
                        document_name
                        == filing.primary_document
                    ),
                )
            )

    return files


def select_relevant_filing_files(
    filing: FilingMetadata,
    files: list[FilingFile],
) -> list[FilingFile]:
    selected = []

    for file in files:
        if file.is_primary:
            selected.append(file)
            continue

        if (
            filing.form
            not in ATTACHMENT_FORMS
        ):
            continue

        suffix = Path(
            file.document_name
        ).suffix.lower()

        if (
            suffix
            not in SUPPORTED_HTML_SUFFIXES
        ):
            continue

        if file.document_type.upper().startswith(
            "EX-99"
        ):
            selected.append(file)

    return selected
