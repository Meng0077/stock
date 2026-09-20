from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from stock_agent.documents.schemas import (
    FilingBlock,
    FilingDocument,
)
from stock_agent.storage.tables import (
    filing_blocks,
)


def save_filing_blocks(
    engine: Engine,
    document: FilingDocument,
) -> int:

    if not document.blocks:
        return 0

    values = [
        {
            "block_id": block.block_id,
            "document_id": block.document_id,
            "document_content_hash": (
                document.content_hash
            ),
            "block_type": block.block_type,
            "text": block.text,
            "start_char": block.start_char,
            "end_char": block.end_char,
            "source_xpath": block.source_xpath,
        }
        for block in document.blocks
    ]

    statement = insert(filing_blocks).values(
        values).on_conflict_do_nothing(
            index_elements={
                filing_blocks.c.block_id,
                filing_blocks.c.document_content_hash,
            }
        ).returning(
            filing_blocks.c.block_id,
        )


    with engine.begin() as connection:
        result = connection.execute(statement)
        return len(result.all())

def get_filing_blocks(
    engine: Engine,
    document_id: str,
    content_hash: str,
) -> list[dict]:
    statement = select(filing_blocks).where(
        filing_blocks.c.document_id == document_id,
        filing_blocks.c.document_content_hash == content_hash,
    )

    with engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()

    return [dict(row) for row in rows]

def get_source_blocks_for_chunk(
    engine: Engine,
    source_block_ids: list[str],
    document_content_hash: str,
) -> list[dict]:
    if not source_block_ids:
        return []

    statement = (
        select(filing_blocks)
        .where(
            filing_blocks.c.block_id.in_(
                source_block_ids
            ),
            filing_blocks.c.document_content_hash
            == document_content_hash,
        )
        .order_by(
            filing_blocks.c.start_char
        )
    )

    with engine.connect() as connection:
        rows = (
            connection.execute(statement)
            .mappings()
            .all()
        )

    return [
        dict(row)
        for row in rows
    ]
