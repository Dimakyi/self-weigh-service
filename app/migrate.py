
"""Apply safe database schema upgrades."""

from sqlalchemy import inspect, text

from app.db import Base, engine
from app import models  # Ensure all models are registered with Base.


def migrate():
    # Create missing tables. Existing tables are not modified by create_all.
    Base.metadata.create_all(engine)

    required_columns = {
        "payment_idempotency_key": "VARCHAR(100)",
        "payment_request_hash": "VARCHAR(64)",
    }

    with engine.begin() as connection:
        inspector = inspect(connection)

        existing_columns = {
            column["name"]
            for column in inspector.get_columns("transactions")
        }

        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE transactions "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )
                print(f"Added transactions.{column_name}")
            else:
                print(f"Already exists: transactions.{column_name}")

    print("Database migration completed successfully.")


if __name__ == "__main__":
    migrate()
