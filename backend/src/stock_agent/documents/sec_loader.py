import hashlib
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Literal

from lxml import etree
from lxml import html as lxml_html

from stock_agent.documents.schemas import (
    FilingBlock,
    FilingDocument,
    FilingFile,
    FilingMetadata,
)
from stock_agent.documents.sec_http import get_sec
from stock_agent.documents.sec_provider import get_filing_files, select_relevant_filing_files

TEXT_BLOCK_TAGS = {
    "address",
    "blockquote",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "pre",
}

SUPPORTED_DOCUMENT_SUFFIXES = {
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


@dataclass(frozen=True)
class SourceBlock:
    block_type: Literal[
        "text",
        "table",
    ]
    text: str
    source_xpath: str


def check_supported_format(
    filing_file: FilingFile,
) -> None:
    suffix = Path(
        filing_file.document_name
    ).suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_SUFFIXES:
        raise FilingLoadError("unsupported_format", filing_file)


def check_content(content: str, filing_file: FilingFile) -> None:
    if not content.strip():
        raise FilingLoadError("empty_content", filing_file)


def download_filing_html(
    filing_file: FilingFile,
) -> str:

    response = get_sec(filing_file.document_url)

    return response.text


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
        line = re.sub(r"[ \t]+", " ", raw_line).strip()

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


def parse_source_html(
    html: str,
):
    html = re.sub(
        r"^\s*<\?xml[^>]*\?>",
        "",
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    return lxml_html.fromstring(html)


def get_tag_name(
    element,
) -> str:
    tag = element.tag

    if not isinstance(
        tag,
        str,
    ):
        return ""

    if tag.startswith("{"):
        return (
            etree.QName(tag)
            .localname
            .lower()
        )

    if ":" in tag:
        return (
            tag
            .rsplit(":", 1)[1]
            .lower()
        )

    return tag.lower()


def is_ix_tag(
    element,
    name: str,
) -> bool:
    raw_tag = element.tag

    if not isinstance(
        raw_tag,
        str,
    ):
        return False

    if (
        raw_tag.lower()
        == f"ix:{name}"
    ):
        return True

    return (
        getattr(
            element,
            "prefix",
            None,
        )
        == "ix"
        and
        get_tag_name(element)
        == name
    )


IGNORED_TAGS = {
    "script",
    "style",
    "noscript",
}


def is_ignored_element(
    element,
) -> bool:
    if get_tag_name(element) in IGNORED_TAGS:
        return True

    if is_ix_tag(element, "header"):
        return True

    if is_ix_tag(element, "hidden"):
        return True

    return False


def extract_element_text(element) -> str:
    parts = []

    def walk(node):
        if node.text:
            parts.append(node.text)

        for child in node:
            if not is_ignored_element(child):
                walk(child)
            if child.tail:
                parts.append(child.tail)

    walk(element)

    return re.sub(r"\s+", " ", "".join(parts)).strip()


def extract_table_text(
    table,
) -> str:
    rows = []

    for row in table.iter():
        if get_tag_name(row) != "tr":
            continue

        ancestor_tables = [
            ancestor
            for ancestor in row.iterancestors()
            if get_tag_name(ancestor) == "table"
        ]
        if not ancestor_tables or ancestor_tables[0] is not table:
            continue

        cells = []

        for cell in row:
            if get_tag_name(cell) not in {"th", "td"}:
                continue

            text = extract_element_text(cell)

            if text:
                cells.append(text)

        if cells:
            rows.append(" | ".join(cells))

    return "\n".join(rows)


def extract_source_blocks(
    root,
) -> list[SourceBlock]:
    blocks = []
    tree = root.getroottree()

    def add_text(text: str | None, element) -> None:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        if normalized:
            blocks.append(
                SourceBlock(
                    block_type="text",
                    text=normalized,
                    source_xpath=tree.getpath(element),
                )
            )

    def contains_block(element) -> bool:
        return any(
            get_tag_name(descendant) in TEXT_BLOCK_TAGS
            or get_tag_name(descendant) == "table"
            for descendant in element.iterdescendants()
            if not is_ignored_element(descendant)
        )

    def walk(element) -> None:
        if is_ignored_element(element):
            return

        if get_tag_name(element) == "table":
            text = extract_table_text(element)
            if text:
                blocks.append(
                    SourceBlock(
                        block_type="table",
                        text=text,
                        source_xpath=tree.getpath(element),
                    )
                )
            return

        buffer = [element.text or ""]

        for child in element:
            if is_ignored_element(child):
                if child.tail:
                    buffer.append(child.tail)
                continue

            child_name = get_tag_name(child)
            child_is_block = (
                child_name in TEXT_BLOCK_TAGS
                or child_name == "table"
                or contains_block(child)
            )

            if child_is_block:
                add_text("".join(buffer), element)
                buffer = []
                walk(child)
            else:
                buffer.append(extract_element_text(child))

            if child.tail:
                buffer.append(child.tail)

        add_text("".join(buffer), element)

    body = next(iter(root.xpath("//body")), root)
    walk(body)

    return blocks

def build_block_id(
    document_id: str,
    index: int,
) -> str:
    return (
        f"{document_id}:"
        f"block:{index}"
    )


def build_filing_blocks(
    document_id: str,
    source_blocks: list[SourceBlock],
) -> tuple[str, list[FilingBlock]]:
    content_parts = []
    filing_blocks = []

    cursor = 0

    for source_block in source_blocks:
        text = normalize_filing_text(
            source_block.text
        )

        if not text:
            continue

        if content_parts:
            separator = "\n\n"

            content_parts.append(
                separator
            )

            cursor += len(
                separator
            )

        start_char = cursor

        content_parts.append(
            text
        )

        cursor += len(text)

        end_char = cursor

        block_index = len(
            filing_blocks
        )

        filing_blocks.append(
            FilingBlock(
                block_id=build_block_id(
                    document_id,
                    block_index,
                ),
                document_id=document_id,
                block_type=(
                    source_block.block_type
                ),
                text=text,
                start_char=start_char,
                end_char=end_char,
                source_xpath=(
                    source_block.source_xpath
                ),
            )
        )

    content = "".join(
        content_parts
    )

    return (
        content,
        filing_blocks,
    )






def load_filing_document(
    filing: FilingMetadata,
    filing_file: FilingFile,
) -> FilingDocument:
    check_supported_format(filing_file)

    html = download_filing_html(filing_file)

    document_id = build_document_id(filing, filing_file)
    root = parse_source_html(html)
    source_blocks = extract_source_blocks(root)
    content, blocks = build_filing_blocks(document_id, source_blocks)

    check_content(content, filing_file)

    content_hash = build_content_hash(content=content)
    return FilingDocument(
        document_id=document_id,
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
        blocks=blocks,
    )


def load_relevant_filing_documents(
    filing: FilingMetadata,
) -> list[FilingDocument]:
    filing_files = get_filing_files(filing)
    relevant_files = select_relevant_filing_files(filing, files=filing_files)
    return [load_filing_document(filing, filing_file) for filing_file in relevant_files]
