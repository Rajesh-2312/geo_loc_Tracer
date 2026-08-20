"""Shared pytest fixtures: a fresh app + client backed by a temporary DB."""
import sqlite3
import sys
from pathlib import Path

import pytest

# Make the project root importable when pytest runs from anywhere.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_tracer.db"


@pytest.fixture
def app(db_path):
    # Force the SQLite backend for tests even if a .env configures Supabase.
    return create_app(
        {
            "DB_PATH": str(db_path),
            "TESTING": True,
            "SUPABASE_URL": None,
            "SUPABASE_SERVICE_KEY": None,
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_session(client):
    """Create a session and return its useful fields."""
    def _make(label="Mom — got home safe?", expiry_minutes=None, max_members=None):
        payload = {"label": label}
        if expiry_minutes is not None:
            payload["expiry_minutes"] = expiry_minutes
        if max_members is not None:
            payload["max_members"] = max_members
        resp = client.post("/api/sessions", json=payload)
        data = resp.get_json()
        data["owner_key"] = data["dashboard_url"].split("key=")[1]
        return data
    return _make


@pytest.fixture
def join_member(client):
    """Join a session as a member; returns the join response JSON."""
    def _join(share_token, name="Alex", member_token=None):
        payload = {"name": name}
        if member_token is not None:
            payload["member_token"] = member_token
        return client.post(f"/api/sessions/{share_token}/join", json=payload)
    return _join


@pytest.fixture
def expire_session(db_path):
    """Force a session's expiry into the past, simulating an elapsed lifetime."""
    def _expire(share_token):
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE sessions SET expires_at = ? WHERE share_token = ?",
                ("2000-01-01T00:00:00+00:00", share_token),
            )
            conn.commit()
        finally:
            conn.close()
    return _expire
