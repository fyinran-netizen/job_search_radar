"""SQLite database initialization and schema migration."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


JOB_COLUMNS = (
    "id, company_name, company_type, title, locations, description, requirements, "
    "recruitment_type, graduation_years, graduation_start, graduation_end, "
    "graduation_requirement, deadline, education_levels, apply_url, source_url, "
    "source_name, is_official, deduplication_key, status, notes, first_seen_at, "
    "last_seen_at, created_at, updated_at"
)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def connection_scope(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _create_jobs(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            company_type TEXT,
            title TEXT NOT NULL,
            locations TEXT NOT NULL,
            description TEXT,
            requirements TEXT,
            recruitment_type TEXT,
            graduation_years TEXT NOT NULL,
            graduation_start TEXT,
            graduation_end TEXT,
            graduation_requirement TEXT,
            deadline TEXT,
            education_levels TEXT NOT NULL,
            apply_url TEXT,
            source_url TEXT,
            source_name TEXT NOT NULL,
            is_official INTEGER NOT NULL,
            deduplication_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL,
            notes TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)


def initialize_database(db_path: Path) -> None:
    with connection_scope(db_path) as connection:
        existing = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
        if existing is None:
            _create_jobs(connection)
        else:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
            required = set(JOB_COLUMNS.split(", "))
            if not required.issubset(columns) or {"published_at", "normalized_location", "match_score"} & columns:
                connection.execute("ALTER TABLE jobs RENAME TO jobs_legacy_migration")
                _create_jobs(connection)
                # Preserve user state while intentionally dropping obsolete facts and match placeholders.
                old = {row[1] for row in connection.execute("PRAGMA table_info(jobs_legacy_migration)")}
                required_old = {"id", "company_name", "title", "source_name"}
                if required_old.issubset(old):
                    def col(name: str, fallback: str) -> str:
                        return name if name in old else fallback
                    connection.execute(f"""
                        INSERT INTO jobs (id, company_name, company_type, title, locations, description, requirements,
                            recruitment_type, graduation_years, graduation_start, graduation_end, graduation_requirement,
                            deadline, education_levels, apply_url, source_url, source_name, is_official, deduplication_key,
                            status, notes, first_seen_at, last_seen_at, created_at, updated_at)
                        SELECT id, company_name, {col('company_type', 'NULL')}, title,
                            CASE WHEN {col('location', 'NULL')} IS NULL THEN '[]' ELSE json_array({col('location', 'NULL')}) END,
                            {col('description', 'NULL')}, {col('requirements', 'NULL')}, {col('recruitment_type', 'NULL')},
                            {col('graduation_years', "'[]'")}, NULL, NULL, NULL, {col('deadline', 'NULL')}, '[]',
                            {col('apply_url', 'NULL')}, {col('source_url', 'NULL')}, source_name,
                            COALESCE({col('is_official', '0')}, 0), 'legacy|' || id,
                            COALESCE({col('status', "'未查看'")}, '未查看'), COALESCE({col('notes', "''")}, ''),
                            COALESCE({col('first_seen_at', "datetime('now')")}, datetime('now')),
                            COALESCE({col('last_seen_at', "datetime('now')")}, datetime('now')),
                            COALESCE({col('created_at', "datetime('now')")}, datetime('now')),
                            COALESCE({col('updated_at', "datetime('now')")}, datetime('now'))
                        FROM jobs_legacy_migration
                    """)
                connection.execute("DROP TABLE jobs_legacy_migration")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
