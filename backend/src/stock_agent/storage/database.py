import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from stock_agent.storage.tables import metadata


def build_database_url() -> str:
    return os.environ["STOCK_AGENT_DATABASE_URL"]


def create_database_engine() -> Engine:
    return create_engine(
        build_database_url(),
    )


def verify_database_connection(
    engine: Engine,
) -> tuple[str, str, str]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    current_database(),
                    current_user,
                    '[1,2,3]'::vector
                """
            )
        ).one()

    return (
        row[0],
        row[1],
        row[2],
    )


def create_database_tables(
    engine: Engine,
) -> None:
    metadata.create_all(engine)
