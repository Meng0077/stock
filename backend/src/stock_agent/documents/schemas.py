from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

SEC_HTML_PARSER_VERSION = "sec-html-v1"

Form = Literal[
    "10-K",
    "10-Q",
    "20-F",
    "40-F",
    "6-K",
    "10-K/A",
    "10-Q/A",
    "20-F/A",
    "40-F/A",
    "6-K/A",
    "8-K",
]


class FilingMetadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    company_id: str
    cik: str

    form: Form

    filing_date: date
    accepted_at: AwareDatetime
    report_date: date | None = None

    accession_number: str
    primary_document: str
    document_url: str


class FilingBlock(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    block_id: str
    document_id: str

    block_type: Literal[
        "text",
        "table",
    ]

    text: str

    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)

    source_xpath: str


class FilingDocument(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    document_id: str

    company_id: str
    cik: str

    form: Form

    filing_date: date
    report_date: date | None = None
    accepted_at: AwareDatetime | None = None

    accession_number: str

    document_name: str
    document_type: str
    is_primary: bool

    source_url: str

    content: str
    content_hash: str

    blocks: list[FilingBlock]


class FilingFile(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    sequence: str | None = None
    document_name: str
    document_type: str
    description: str | None = None

    document_url: str
    is_primary: bool


class DocumentChunk(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )

    chunk_id: str
    document_id: str
    document_content_hash: str
    source_url: str

    company_id: str

    chunk_index: int = Field(ge=0)

    start_char: int = Field(ge=0)

    end_char: int = Field(ge=0)

    content: str

    source_block_ids: list[str]
    source_xpaths: list[str]


"""
    evidence_id
    ↓
    DocumentChunk
    ↓
    source_block_ids
    ↓
    FilingBlock[]
    ↓
    source_xpath
    ↓
    SEC 原始 XHTML
"""
