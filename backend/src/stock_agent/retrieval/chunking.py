from stock_agent.documents.schemas import (
    DocumentChunk,
    FilingDocument,
)
from stock_agent.retrieval.schemas import (
    IndexConfig,
    build_chunk_config_id,
)

"""
chunk 的身份
document identity
+
document content version
+
index config
+
chunk index
"""



def build_chunk_id(
    document: FilingDocument,
    config: IndexConfig,
    chunk_index: int,
) -> str:
    config_id = build_chunk_config_id(config)
    return (
        f"{document.document_id}:"
        f"{document.content_hash}:"
        f"{config_id}:"
        f"chunk:{chunk_index}"
    )

def choose_chunk_end(
    content: str,
    start: int,
    config: IndexConfig,
) -> int:
    hard_end = min(
        start + config.chunk_size,
        len(content),
    )

    if hard_end == len(content):
        return hard_end

    min_chunk_length = max( config.chunk_size // 2, config.chunk_overlap + 1,)

    min_end = min( start + min_chunk_length, hard_end,)

    for separator in ( "\n\n", "\n", " ",):
        index = content.rfind( separator, min_end, hard_end,)

        if index > start: return index

    return hard_end

def split_filing_document(
    document: FilingDocument,
    config: IndexConfig,
) -> list[DocumentChunk]:
    content = document.content

    if not content:
        raise ValueError("document content is empty")
    chunks = []

    start = 0
    while start < len(content):
        end = choose_chunk_end(content, start, config)
        chunk_content = content[start:end]

        source_blocks = [
            block
            for block in document.blocks
            if block.start_char < end and block.end_char > start
        ]

        chunk_index = len(chunks)

        chunks.append(
            DocumentChunk(
                chunk_id=build_chunk_id(document, config, chunk_index),
                document_id=document.document_id,
                document_content_hash=document.content_hash,
                source_url=document.source_url,
                company_id=document.company_id,
                chunk_index=chunk_index,
                start_char=start,
                end_char=end,
                content=chunk_content,
                source_block_ids=[block.block_id for block in source_blocks],
                source_xpaths=[block.source_xpath for block in source_blocks],
            )
        )
        if end == len(content):
            break

        # 允许一部分上下重合，保留上下文
        start = end - config.chunk_overlap

    return chunks

def build_evidence_id(
    chunk_id: str,
) -> str:
    return f"rag:{chunk_id}"
