from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

from stock_agent.storage.tables import (
    company_indexes,
)

def save_company_index(
    engine: Engine,
    company_id: str,
    as_of: datetime,
    index_config_id: str,
    document_versions: dict[str, str],
    chunk_count: int,
) -> bool:

    statement = insert(company_indexes).values(
        company_id=company_id,
        as_of=as_of,
        index_config_id=index_config_id,
        document_versions=document_versions,
        chunk_count=chunk_count,
    ).on_conflict_do_nothing(
        index_elements=[
            company_indexes.c.company_id,
            company_indexes.c.as_of,
            company_indexes.c.index_config_id,
        ]
    ).returning(
        company_indexes.c.company_id,
    )

    with engine.begin() as connection:
        result = connection.execute(statement)
        return result.first() is not None

def get_company_index(
    engine: Engine,
    company_id: str,
    as_of: datetime,
    index_config_id: str,
) -> dict | None:
    statement = (
        select(company_indexes)
        .where(
            company_indexes.c.company_id == company_id,
            company_indexes.c.as_of == as_of,
            company_indexes.c.index_config_id == index_config_id,
        )
    )

    with engine.connect() as connection:
        row = connection.execute(statement).mappings().one_or_none()

    return dict(row) if row else None


# 根据 company_id + as_of + index_config_id， 查找之前有没有存储过
def get_latest_compatible_company_index(
    engine: Engine,
    company_id: str,
    as_of: datetime,
    index_config_id: str,
) -> dict | None:
    statement = (
        select(company_indexes)
        .where(
            company_indexes.c.company_id == company_id,
            company_indexes.c.as_of < as_of,
            company_indexes.c.index_config_id == index_config_id,
        )
        .order_by(company_indexes.c.as_of.desc())
        .limit(1)
    )

    with engine.connect() as connection:
        row = connection.execute(statement).mappings().one_or_none()

    return dict(row) if row else None
