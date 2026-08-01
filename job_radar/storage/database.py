"""SQLite database initialization."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with row dictionaries enabled."""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def connection_scope(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, and always close it."""

    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(db_path: Path) -> None:
    """Create the jobs table if it does not exist."""

    with connection_scope(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                company_type TEXT,
                title TEXT NOT NULL,
                location TEXT NOT NULL,
                description TEXT,
                requirements TEXT,
                recruitment_type TEXT,
                graduation_years TEXT NOT NULL,
                published_at TEXT,
                deadline TEXT,
                apply_url TEXT,
                source_url TEXT,
                source_name TEXT NOT NULL,
                is_official INTEGER NOT NULL,
                normalized_company_name TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                normalized_location TEXT NOT NULL,
                deduplication_key TEXT NOT NULL UNIQUE,
                match_score INTEGER NOT NULL,
                match_reasons TEXT NOT NULL,
                missing_requirements TEXT NOT NULL,
                status TEXT NOT NULL,
                notes TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score)")
