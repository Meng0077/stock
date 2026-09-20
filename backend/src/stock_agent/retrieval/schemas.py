

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stock_agent.documents.schemas import SEC_HTML_PARSER_VERSION


class IndexConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    chunk_size: int = Field(gt=0)
    chunk_overlap: int = Field(ge=0)

    embedding_model: str
    parser_version: str = SEC_HTML_PARSER_VERSION


    @model_validator(mode="after")
    def validate_overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self

DEFAULT_INDEX_CONFIG = IndexConfig(
    chunk_size=800,
    chunk_overlap=100,
    embedding_model=(
        "sentence-transformers/"
        "all-mpnet-base-v2"
    ),
)


def build_index_config_id(
    config: IndexConfig,
) -> str:
    payload = json.dumps(
        config.model_dump(),
        sort_keys=True,
        separators=[",", ":"],
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def build_chunk_config_id(config: IndexConfig,) -> str:
    payload = json.dumps(
        {
            "chunk_size": config.chunk_size,
            "chunk_overlap": config.chunk_overlap
        },
        sort_keys=True,
        separators=[",", ":"],
    )

    return hashlib.sha256(payload.encode('utf-8')).hexdigest()
