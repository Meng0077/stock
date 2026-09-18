from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

class FilingMetadata(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    company_id: str
    cik: str

    form: Literal[
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

    filing_date: date
    accepted_at: AwareDatetime
    report_date: date | None = None

    accession_number: str
    primary_document: str
    document_url: str
