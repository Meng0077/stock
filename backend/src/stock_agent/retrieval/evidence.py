def parse_rag_evidence_id(
    evidence_id: str,
) -> str:

    prefix = "rag:"

    if not evidence_id.startswith(prefix):
        raise ValueError(
            "not a RAG evidence id"
        )
    chunk_id = evidence_id[len(prefix):]

    if not chunk_id:
        raise ValueError(
            "empty chunk id"
        )

    return chunk_id
