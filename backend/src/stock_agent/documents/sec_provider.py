
from datetime import date, datetime, timezone

from stock_agent.documents.schemas import FilingMetadata

import httpx


SEC_TICKERS_URL = (
    "https://www.sec.gov/files/company_tickers.json"
)

SEC_HEADERS = {
    "User-Agent": "demo-agent 314885503@qq.com",
}

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

class UnknownTickerError(ValueError):
    def __init__(self, company_id: str):
        self.company_id = company_id

        super().__init__(
            f"SEC 未找到 ticker: {company_id}"
        )


def ticker_to_cik(
    company_id: str,
) -> str | None:
    response = httpx.get(
        SEC_TICKERS_URL,
        headers=SEC_HEADERS,
        timeout=30.0,
    )

    response.raise_for_status()
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
    response = httpx.get(
            f"{SEC_SUBMISSIONS_URL}/CIK{cik}.json",
            headers=SEC_HEADERS,
            timeout=30.0,
        )
    response.raise_for_status()

    return response.json()

def build_document_url(
    cik: str,
    accession_number: str,
    primary_document: str,
) -> str:
    cik_path = str(int(cik))
    accession_path = accession_number.replace(
        "-",
        "",
    )
    return f"{SEC_ARCHIVES_URL}/{cik_path}/{accession_path}/{primary_document}"


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
        document_url=build_document_url(cik=cik, accession_number=accession_number, primary_document=primary_document),
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
