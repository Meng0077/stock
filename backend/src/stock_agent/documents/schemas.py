from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

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

    block_type: Literal[
        "text",
        "table",
    ]

    text: str

    start_char: int
    end_char: int

    source_xpath: str | None = None


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

    # blocks: list[FilingBlock]

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
