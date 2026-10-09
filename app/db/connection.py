"""
Shared Postgres connection helper.

Every later stage (alert parser, fetcher, matcher, drafter, mailer) imports
get_connection() from here rather than opening its own connection, so there's
one place that knows about DATABASE_URL.
"""

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection():
    """Open a new connection using DATABASE_URL from the environment."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Check your .env file and docker-compose.yml."
        )
    return psycopg2.connect(database_url)


def init_db():
    """Create the jobs table if it doesn't exist yet. Safe to run on every startup."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_PATH.read_text())
        conn.commit()
    print("Database initialized (jobs table ready).")


if __name__ == "__main__":
    # Run this directly to test the connection and create the table:
    #   docker compose run --rm app python db/connection.py
    init_db()
