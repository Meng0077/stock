from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    MetaData,
    String,
    Numeric,
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


financial_facts = Table(
    "financial_facts",
    metadata,

    # Day19-2 会正式定义这个 fact_id 怎么生成。
    #
    # 它同时会成为：
    #
    # financial evidence_id
    #          ↓
    # financial_facts.fact_id
    #
    Column(
        "fact_id",
        String,
        primary_key=True,
    ),

    # 项目内部公司标识，例如 NVDA。
    Column(
        "company_id",
        String,
        nullable=False,
        index=True,
    ),

    # XBRL concept，例如：
    # NetIncomeLoss
    # Assets
    Column(
        "concept",
        String,
        nullable=False,
        index=True,
    ),

    # 财务数值。
    Column(
        "value",
        Numeric,
        nullable=False,
    ),

    # USD / shares / USD/shares 等。
    Column(
        "unit",
        String,
        nullable=False,
    ),

    # duration fact 有 start_date；
    # instant fact 为 NULL。
    Column(
        "start_date",
        Date,
        nullable=True,
    ),

    Column(
        "end_date",
        Date,
        nullable=False,
        index=True,
    ),

    # SEC Company Facts 的 filed 字段。
    #
    # 当前 Financial 模块的 as_of
    # 就是基于这个日期过滤。
    Column(
        "filed_date",
        Date,
        nullable=False,
        index=True,
    ),

    # 10-Q / 10-K 等。
    Column(
        "form",
        String,
        nullable=False,
    ),

    # SEC accession number。
    Column(
        "accession_number",
        String,
        nullable=False,
        index=True,
    ),

    # SEC fy。
    Column(
        "fiscal_year",
        Integer,
        nullable=True,
    ),

    # Q1 / Q2 / Q3 / FY。
    Column(
        "fiscal_period",
        String,
        nullable=True,
    ),

    # CY2026Q2 等。
    # 并不是每条 entry 都有。
    Column(
        "frame",
        String,
        nullable=True,
    ),
)


financial_fact_syncs = Table(
    "financial_fact_syncs",
    metadata,

    # 一个 sync state 对应：
    #
    # company
    # + concept
    # + unit
    #
    # 所以这里直接使用联合主键。
    Column(
        "company_id",
        String,
        primary_key=True,
    ),

    Column(
        "concept",
        String,
        primary_key=True,
    ),

    Column(
        "unit",
        String,
        primary_key=True,
    ),

    # 保存 CIK，
    # 方便知道这个同步状态对应哪个 SEC entity。
    Column(
        "cik",
        String,
        nullable=False,
    ),

    # 表示：
    #
    # 这组 financial facts 已经成功同步到哪个日期。
    #
    # 如果：
    #
    # request.as_of <= covered_through
    #
    # 第一版就认为缓存可以直接复用。
    Column(
        "covered_through",
        Date,
        nullable=False,
    ),
)
