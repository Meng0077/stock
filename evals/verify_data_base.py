from sqlalchemy import text

from stock_agent.storage.database import (
    create_database_engine,
    verify_database_connection,
)


def main():
    engine = create_database_engine()
    database, user, vector = verify_database_connection(engine)

    with engine.connect() as connection:
        version = connection.execute(
            text("""
                SELECT extversion
                FROM pg_extension
                WHERE extname = 'vector'
            """)).scalar_one()
    print(
        "PASS database connection:",
        database,
        user,
    )

    print("vector check:", vector)
    print(
        "pgvector version:",
        version,
    )

if __name__ == "__main__":
    main()
