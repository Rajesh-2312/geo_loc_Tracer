"""SQLite helpers for the location tracer.

A single database file (tracer.db) holds sessions and their location pings.
The connection is stored on Flask's application context ``g`` so each request
reuses one connection and it is closed automatically when the request ends.
"""

import sqlite3
from pathlib import Path

from flask import current_app, g

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "tracer.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"


def get_db() -> sqlite3.Connection:
    """Return the request-scoped SQLite connection, opening it if needed."""
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config.get("DB_PATH", DB_PATH),
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        # Enforce the ON DELETE CASCADE declared in schema.sql.
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(exc: BaseException | None = None) -> None:
    """Close the request-scoped connection, if one was opened."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app) -> None:
    """Create tables from schema.sql if they do not already exist."""
    db_path = app.config.get("DB_PATH", DB_PATH)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created.

    ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so a database
    made by an earlier version needs its new columns added explicitly. (New
    tables such as ``members`` are handled by the schema's CREATE ... IF NOT
    EXISTS on every init.)
    """
    session_cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "expires_at" not in session_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN expires_at TEXT")
    if "max_members" not in session_cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN max_members INTEGER NOT NULL DEFAULT 5")

    location_cols = {row[1] for row in conn.execute("PRAGMA table_info(locations)")}
    if "member_id" not in location_cols:
        conn.execute("ALTER TABLE locations ADD COLUMN member_id INTEGER")


def init_app(app) -> None:
    """Wire teardown handling into the Flask app."""
    app.teardown_appcontext(close_db)
