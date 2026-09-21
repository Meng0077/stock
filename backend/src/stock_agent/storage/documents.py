from sqlalchemy.engine import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select, tuple_

from stock_agent.documents.schemas import FilingDocument
from stock_agent.storage.tables import filing_documents

def save_filing_document(
    engine: Engine,
    document: FilingDocument,
) -> bool:
    statement = insert(filing_documents).values(
        document_id=document.document_id,
        content_hash=document.content_hash,
        company_id=document.company_id,
        cik=document.cik,
        form=document.form,
        filing_date=document.filing_date,
        report_date=document.report_date,
        accepted_at=document.accepted_at,
        accession_number=document.accession_number,
        document_name=document.document_name,
        document_type=document.document_type,
        is_primary=document.is_primary,
        source_url=document.source_url,
        content=document.content,
    ).on_conflict_do_nothing(
        index_elements=[
            filing_documents.c.document_id,
            filing_documents.c.content_hash,
        ]
    )

    with engine.begin() as connection:
        result = connection.execute(statement)

    return result.rowcount == 1


def get_filing_document(
    engine: Engine,
    document_id: str,
    content_hash: str,
) -> dict | None:
    statement = select(filing_documents).where(
        filing_documents.c.document_id == document_id,
        filing_documents.c.content_hash == content_hash
    )

    with engine.connect() as connection:
        row = connection.execute(statement).mappings().one_or_none()

    if row is None:
        return None

    return dict(row)

# 根据document_versions 查询 documents
def get_document_versions(
    engine: Engine,
    document_versions: dict[str, str],
) -> list[dict]:
    if not document_versions:
        return []

    version_pairs = [
        (
            document_id,
            content_hash,
        )
        for document_id, content_hash
        in document_versions.items()
    ]

    statement = select(
        filing_documents
    ).where(
        tuple_(
            filing_documents.c.document_id,
            filing_documents.c.content_hash,
        ).in_(version_pairs)
    )

    with engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()

    return [dict(row) for row in rows]

# 根据document_versions 先查询 documents，最终得到accession_number
def get_indexed_accession_numbers(
    engine: Engine,
    document_versions: dict[str, str],
) -> set[str]:
    documents = get_document_versions(engine, document_versions)
    return {
        document["accession_number"]
        for document in documents
    }
