from sqlalchemy.engine import Engine

from stock_agent.retrieval.evidence import (
    parse_rag_evidence_id,
)
from stock_agent.storage.blocks import (
    get_source_blocks_for_chunk,
)
from stock_agent.storage.chunks import (
    get_document_chunk,
)
from stock_agent.storage.documents import (
    get_filing_document,
)


def resolve_rag_evidence(
    engine: Engine,
    evidence_id: str,
) -> dict | None:

    chunk_id = parse_rag_evidence_id(evidence_id)
    chunk = get_document_chunk(engine, chunk_id)
    if chunk is None:
        return None

    blocks = get_source_blocks_for_chunk(
        engine,
        source_block_ids=chunk["source_block_ids"],
        document_content_hash=chunk["document_content_hash"]
    )

    document = get_filing_document(engine, chunk["document_id"], chunk["document_content_hash"],)
    if document is None:
        raise RuntimeError(
            "chunk document not found"
        )

    return {
        "evidence_id": evidence_id,
        "chunk": chunk,
        "blocks": blocks,
        "document": document,
    }
