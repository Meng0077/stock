from stock_agent.documents.sec_loader import (
    FilingLoadError,
    build_content_hash,
    check_content,
    get_filing_files,
    load_filing_document,
    select_relevant_filing_files,
)
from stock_agent.documents.schemas import FilingFile
from stock_agent.documents.sec_provider import (
    get_recent_filings,
)


def verify_real_filing(
    form: str,
) -> bool:
    filings = get_recent_filings(
        company_id="NVDA",
        forms={form},
        limit=1,
    )

    if not filings:
        print(
            "FAIL",
            form,
            "no filing",
        )
        return False

    filing = filings[0]

    files = get_filing_files(filing)
    selected_files = select_relevant_filing_files(filing, files)


    documents = [
        load_filing_document(filing, filing_file)
        for filing_file in selected_files
    ]

    if not documents:
        print(
            "FAIL",
            form,
            "no selected documents",
        )
        return False

    files_by_name = {
        filing_file.document_name: filing_file
        for filing_file in selected_files
    }
    for document in documents:
        filing_file = files_by_name[document.document_name]
        if not document.content:
            print("FAIL", form, document.document_name, "empty content")
            return False
        if document.company_id != "NVDA":
            print("FAIL", form, document.document_name, "wrong company")
            return False
        if document.form != form:
            print("FAIL", form, document.document_name, "wrong form")
            return False
        if document.source_url != filing_file.document_url:
            print("FAIL", form, document.document_name, "wrong source")
            return False
        if document.is_primary != filing_file.is_primary:
            print("FAIL", form, document.document_name, "wrong primary flag")
            return False
        if build_content_hash(document.content) != document.content_hash:
            print("FAIL", form, document.document_name, "wrong hash")
            return False

    print(
        "PASS",
        form,
        len(documents),
        sum(len(document.content) for document in documents),
    )

    return True

def verify_stable_document() -> bool:
    filing = get_recent_filings(
        company_id="NVDA",
        forms={"10-Q"},
        limit=1,
    )[0]

    filing_file = select_relevant_filing_files(
        filing,
        get_filing_files(filing),
    )[0]

    first = load_filing_document(
        filing,
        filing_file,
    )

    second = load_filing_document(
        filing,
        filing_file,
    )

    if (
        first.document_id
        != second.document_id
    ):
        print(
            "FAIL",
            "unstable document_id",
        )
        return False

    if (
        first.content_hash
        != second.content_hash
    ):
        print(
            "FAIL",
            "unstable content_hash",
        )
        return False

    if (
        first.content
        != second.content
    ):
        print(
            "FAIL",
            "unstable content",
        )
        return False

    print(
        "PASS",
        "stable_document",
    )

    return True

def verify_unsupported_format() -> bool:
    filing = get_recent_filings(
        company_id="NVDA",
        limit=1,
    )[0]

    bad_file = FilingFile(
        document_name="example.pdf",
        document_type=filing.form,
        document_url="https://example.com/example.pdf",
        is_primary=True,
    )

    try:
        load_filing_document(
            filing,
            bad_file,
        )
    except FilingLoadError as error:
        if (
            error.code
            == "unsupported_format"
        ):
            print(
                "PASS",
                "unsupported_format",
            )
            return True

    print(
        "FAIL",
        "unsupported_format",
    )

    return False

def verify_empty_content() -> bool:
    filing = get_recent_filings(
        company_id="NVDA",
        limit=1,
    )[0]
    empty_file = FilingFile(
        document_name=filing.primary_document,
        document_type=filing.form,
        document_url=filing.document_url,
        is_primary=True,
    )

    try:
        check_content(
            "",
            empty_file,
        )
    except FilingLoadError as error:
        if (
            error.code
            == "empty_content"
        ):
            print(
                "PASS",
                "empty_content",
            )
            return True

    print(
        "FAIL",
        "empty_content",
    )

    return False

def main():
    results = [
        verify_real_filing(
            "10-Q"
        ),
        verify_real_filing(
            "10-K"
        ),
        verify_stable_document(),
        verify_unsupported_format(),
        verify_empty_content(),
    ]

    if not all(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
