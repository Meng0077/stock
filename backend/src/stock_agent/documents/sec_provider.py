from datetime import date, datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from stock_agent.documents.schemas import FilingFile, FilingMetadata
from stock_agent.documents.sec_http import SEC_HEADERS, get_sec


SEC_TICKERS_URL = (
    "https://www.sec.gov/files/company_tickers.json"
)

SEC_SUBMISSIONS_URL = (
    "https://data.sec.gov/submissions"
)

SUPPORTED_FORMS = {
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
}

SEC_ARCHIVES_URL = (
    "https://www.sec.gov/Archives/edgar/data"
)


ATTACHMENT_FORMS = {
    "6-K",
    "6-K/A",
}

SUPPORTED_HTML_SUFFIXES = {
    ".htm",
    ".html",
}


class UnknownTickerError(ValueError):
    def __init__(self, company_id: str):
        self.company_id = company_id

        super().__init__(
            f"SEC 未找到 ticker: {company_id}"
        )


def ticker_to_cik(
    company_id: str,
) -> str | None:
    response = get_sec(SEC_TICKERS_URL)
    companies = response.json()
    ticker = company_id.upper()

    for company in companies.values():
        if company["ticker"].upper() == ticker:
            return str(
                company["cik_str"]
            ).zfill(10)
    return None

def get_company_submissions(
    cik: str,
) -> dict:
    response = get_sec(
        f"{SEC_SUBMISSIONS_URL}/CIK{cik}.json"
    )

    return response.json()

def build_document_url(
    cik: str,
    accession_number: str,
    document_name: str,
) -> str:
    cik_path = str(int(cik))
    accession_path = accession_number.replace(
        "-",
        "",
    )
    return f"{SEC_ARCHIVES_URL}/{cik_path}/{accession_path}/{document_name}"


def build_filing_metadata(
    company_id: str,
    cik: str,
    recent: dict,
    index: int,
) -> FilingMetadata:
    report_date_text = recent["reportDate"][index]
    accession_number=recent["accessionNumber"][index]
    primary_document=recent["primaryDocument"][index]



    return FilingMetadata(
        company_id=company_id.upper(),
        cik=cik,
        form=recent["form"][index],
        filing_date=date.fromisoformat(recent["filingDate"][index]),
        accepted_at=recent["acceptanceDateTime"][index],
        report_date=(date.fromisoformat(report_date_text) if report_date_text else None),
        accession_number=accession_number,
        primary_document=primary_document,
        document_url=build_document_url(cik=cik, accession_number=accession_number, document_name=primary_document),
    )

def build_recent_filings(
    company_id: str,
    cik: str,
    recent: dict,
    forms: set[str],
) -> list[FilingMetadata]:
    filings = []

    for index, form in enumerate( recent["form"] ):
        if form not in forms:
            continue
        filing = build_filing_metadata(company_id=company_id, cik=cik, recent=recent, index=index)
        filings.append(filing)
    return filings

def get_recent_filings(
    company_id: str,
    as_of: datetime | None = None,
    forms: set[str] | None = None,
    limit: int = 5,
) -> list[FilingMetadata]:
    if as_of is None:
        as_of = datetime.now(timezone.utc)
    if as_of.utcoffset() is None:
        raise ValueError("as_of 必须包含时区")
    if forms is None:
        forms = set(SUPPORTED_FORMS)


    cik = ticker_to_cik(company_id)
    if cik is None:
        raise UnknownTickerError(
            company_id
        )
    submissions = get_company_submissions(cik=cik)
    recent=submissions["filings"]["recent"]

    filings = build_recent_filings(
        company_id=company_id,
        cik=cik,
        recent=recent,
        forms=forms
    )

    filings = [filing for filing in filings if filing.accepted_at <= as_of]
    filings.sort(
        key=lambda filing: filing.accepted_at,
        reverse=True,
    )

    return filings[:limit]


def get_filing_files(
    filing: FilingMetadata,
) -> list[FilingFile]:
    index_url = build_document_url(
        cik=filing.cik,
        accession_number=filing.accession_number,
        document_name=f"{filing.accession_number}-index.html",
    )
    response = get_sec(index_url)

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

            sequence = cells[0].get_text(" ", strip=True) or None

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
