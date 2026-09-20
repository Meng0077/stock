from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    Date,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

from stock_agent.retrieval.schemas import DEFAULT_EMBEDDING_DIMENSION

metadata = MetaData()

filing_documents = Table(
    "filing_documents",
    metadata,

    Column(
        "document_id",
        String,
        primary_key=True,
    ),

    Column(
        "content_hash",
        String,
        primary_key=True,
    ),

    Column(
        "company_id",
        String,
        nullable=False,
    ),

    Column(
        "cik",
        String,
        nullable=False,
    ),

    Column(
        "form",
        String,
        nullable=False,
    ),

    Column(
        "filing_date",
        Date,
        nullable=False,
    ),

    Column(
        "report_date",
        Date,
        nullable=True,
    ),

    Column(
        "accepted_at",
        DateTime(timezone=True),
        nullable=True,
    ),

    Column(
        "accession_number",
        String,
        nullable=False,
    ),

    Column(
        "document_name",
        String,
        nullable=False,
    ),

    Column(
        "document_type",
        String,
        nullable=False,
    ),

    Column(
        "is_primary",
        Boolean,
        nullable=False,
    ),

    Column(
        "source_url",
        Text,
        nullable=False,
    ),

    Column(
        "content",
        Text,
        nullable=False,
    ),
)

filing_blocks = Table(
    "filing_blocks",
    metadata,

    Column(
        "block_id",
        String,
        nullable=False,
    ),

    Column(
        "document_id",
        String,
        nullable=False,
    ),

    Column(
        "document_content_hash",
        String,
        nullable=False,
    ),

    Column(
        "block_type",
        String,
        nullable=False,
    ),

    Column(
        "text",
        Text,
        nullable=False,
    ),

    Column(
        "start_char",
        Integer,
        nullable=False,
    ),

    Column(
        "end_char",
        Integer,
        nullable=False,
    ),

    Column(
        "source_xpath",
        Text,
        nullable=False,
    ),

    PrimaryKeyConstraint(
        "block_id",
        "document_content_hash",
    ),

    ForeignKeyConstraint(
        [
            "document_id",
            "document_content_hash",
        ],
        [
            "filing_documents.document_id",
            "filing_documents.content_hash",
        ],
    ),
)

document_chunks = Table(
    "document_chunks",
    metadata,

    Column(
        "chunk_id",
        String,
        primary_key=True,
    ),

    Column(
        "document_id",
        String,
        nullable=False,
    ),

    Column(
        "document_content_hash",
        String,
        nullable=False,
    ),

    Column(
        "company_id",
        String,
        nullable=False,
    ),

    Column(
        "chunk_config_id",
        String,
        nullable=False,
    ),

    Column(
        "chunk_index",
        Integer,
        nullable=False,
    ),

    Column(
        "start_char",
        Integer,
        nullable=False,
    ),

    Column(
        "end_char",
        Integer,
        nullable=False,
    ),

    Column(
        "content",
        Text,
        nullable=False,
    ),

    Column(
        "source_block_ids",
        ARRAY(String),
        nullable=False,
    ),

    ForeignKeyConstraint(
        [
            "document_id",
            "document_content_hash",
        ],
        [
            "filing_documents.document_id",
            "filing_documents.content_hash",
        ],
    ),
)

chunk_embeddings = Table(
    "chunk_embeddings",
    metadata,

    Column(
        "chunk_id",
        String,
        nullable=False,
    ),

    Column(
        "index_config_id",
        String,
        nullable=False,
    ),

    Column(
        "embedding_model",
        String,
        nullable=False,
    ),

    Column(
        "embedding_revision",
        String,
        nullable=False,
    ),

    Column(
        "embedding_dimension",
        Integer,
        nullable=False,
    ),

    Column(
        "embedding",
        Vector(DEFAULT_EMBEDDING_DIMENSION),
        nullable=False,
    ),

    PrimaryKeyConstraint(
        "chunk_id",
        "index_config_id",
    ),

    ForeignKeyConstraint(
        ["chunk_id"],
        ["document_chunks.chunk_id"],
    ),
)

company_indexes = Table(
    "company_indexes",
    metadata,

    Column(
        "company_id",
        String,
        nullable=False,
    ),

    Column(
        "as_of",
        DateTime(timezone=True),
        nullable=False,
    ),

    Column(
        "index_config_id",
        String,
        nullable=False,
    ),

    Column(
        "document_versions",
        JSONB,
        nullable=False,
    ),

    Column(
        "chunk_count",
        Integer,
        nullable=False,
    ),

    PrimaryKeyConstraint(
        "company_id",
        "as_of",
        "index_config_id",
    ),
)
