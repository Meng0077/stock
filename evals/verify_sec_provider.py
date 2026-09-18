from datetime import datetime, timezone

from stock_agent.documents.sec_provider import (
    get_recent_filings,
    UnknownTickerError
)

def verify_company(company_id: str, as_of: datetime, forms: set[str]) -> bool:
    filings = get_recent_filings(
        company_id=company_id,
        as_of=as_of,
        forms=forms,
        limit=3,
    )

    if not filings:
        print("FAIL", company_id, "no filings")
        return False

    for filing in filings:
        if filing.company_id != company_id:
            print(
                "FAIL",
                company_id,
                "wrong company_id",
            )
            return False

        if filing.form not in forms:
            print(
                "FAIL",
                company_id,
                "wrong form",
                filing.form,
            )
            return False

        if filing.accepted_at > as_of:
            print("FAIL", company_id, "filing accepted after as_of")
            return False

        if not filing.document_url.startswith(
            "https://www.sec.gov/Archives/"
        ):
            print(
                "FAIL",
                company_id,
                "bad url",
            )
            return False

    print("PASS", company_id)

    return True
def verify_unknown_ticker(as_of: datetime) -> bool:
    try:
        filings =get_recent_filings(
            company_id="NOTAREALTICKERXYZ",
            as_of=as_of,
            limit=3,
        )
    except UnknownTickerError:
        print("PASS unknown_ticker")
        return True

    print(
        "FAIL unknown_ticker",
        "expected UnknownTickerError",
    )


    return False


def main():
    as_of = datetime.now(timezone.utc)
    results = [
        verify_company("NVDA", as_of, {"10-K", "10-Q"}),
        verify_company("AMD", as_of, {"10-K", "10-Q"}),
        verify_company("TSM", as_of, {"20-F", "6-K"}),
        verify_unknown_ticker(as_of),
    ]

    if not all(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
