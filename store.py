"""Pluggable storage for sessions, members, and location pings.

Two backends implement the same small interface:

* ``SQLiteStore``  — local file DB (default). Used for local runs and tests.
* ``SupabaseStore`` — Supabase Postgres via its REST (PostgREST) API, using the
  service_role key. The key lives only on the server; the browser never talks
  to Supabase directly.

The backend is chosen by config: if ``SUPABASE_URL`` and ``SUPABASE_SERVICE_KEY``
are set, Supabase is used; otherwise SQLite.

A session may have up to ``max_members`` members. Each member is one device that
joined the link; every location ping belongs to a member so the dashboard can
show each person separately.

Every method returns plain dicts (or lists of dicts) with the same keys, so
``app.py`` does not care which backend is active.
"""

from __future__ import annotations

import requests

import db


def _row(row):
    return dict(row) if row is not None else None


class SQLiteStore:
    """SQLite backend. Relies on Flask's request-scoped connection in db.py."""

    backend = "sqlite"

    # -- sessions -------------------------------------------------------- #
    def create_session(self, share_token, owner_key, label, created_at,
                       expires_at, max_members):
        conn = db.get_db()
        cur = conn.execute(
            "INSERT INTO sessions "
            "(share_token, owner_key, label, created_at, expires_at, max_members, active) "
            "VALUES (?, ?, ?, ?, ?, ?, 1)",
            (share_token, owner_key, label, created_at, expires_at, max_members),
        )
        conn.commit()
        return cur.lastrowid

    def get_session(self, share_token):
        return _row(
            db.get_db().execute(
                "SELECT * FROM sessions WHERE share_token = ?", (share_token,)
            ).fetchone()
        )

    def stop_session(self, session_id):
        conn = db.get_db()
        conn.execute("UPDATE sessions SET active = 0 WHERE id = ?", (session_id,))
        conn.commit()

    # -- members --------------------------------------------------------- #
    def count_members(self, session_id):
        return db.get_db().execute(
            "SELECT COUNT(*) FROM members WHERE session_id = ?", (session_id,)
        ).fetchone()[0]

    def add_member(self, session_id, member_token, name, joined_at):
        conn = db.get_db()
        cur = conn.execute(
            "INSERT INTO members (session_id, member_token, name, joined_at, last_seen) "
            "VALUES (?, ?, ?, ?, NULL)",
            (session_id, member_token, name, joined_at),
        )
        conn.commit()
        return cur.lastrowid

    def get_member(self, session_id, member_token):
        return _row(
            db.get_db().execute(
                "SELECT * FROM members WHERE session_id = ? AND member_token = ?",
                (session_id, member_token),
            ).fetchone()
        )

    def list_members(self, session_id):
        rows = db.get_db().execute(
            "SELECT id, name, joined_at, last_seen FROM members "
            "WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def touch_member(self, member_id, last_seen):
        conn = db.get_db()
        conn.execute(
            "UPDATE members SET last_seen = ? WHERE id = ?", (last_seen, member_id)
        )
        conn.commit()

    # -- locations ------------------------------------------------------- #
    def insert_location(self, session_id, member_id, lat, lng, accuracy,
                        client_ts, server_ts):
        conn = db.get_db()
        conn.execute(
            "INSERT INTO locations "
            "(session_id, member_id, lat, lng, accuracy, client_ts, server_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, member_id, lat, lng, accuracy, client_ts, server_ts),
        )
        conn.commit()

    def recent_locations(self, session_id, limit):
        """Most recent locations across all members (newest first)."""
        rows = db.get_db().execute(
            "SELECT id, member_id, lat, lng, accuracy, client_ts, server_ts "
            "FROM locations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


class SupabaseStore:
    """Supabase Postgres backend via the PostgREST API (service_role key)."""

    backend = "supabase"

    def __init__(self, url: str, service_key: str, timeout: float = 10.0):
        self.rest = url.rstrip("/") + "/rest/v1"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            }
        )

    def _post(self, table, payload, return_rows=False):
        headers = {"Prefer": "return=representation"} if return_rows else {}
        r = self.session.post(
            f"{self.rest}/{table}", json=payload, headers=headers, timeout=self.timeout
        )
        r.raise_for_status()
        return r.json() if return_rows else None

    def _get(self, table, params):
        r = self.session.get(
            f"{self.rest}/{table}", params=params, timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()

    def _patch(self, table, params, payload):
        r = self.session.patch(
            f"{self.rest}/{table}", params=params, json=payload, timeout=self.timeout
        )
        r.raise_for_status()

    # -- sessions -------------------------------------------------------- #
    def create_session(self, share_token, owner_key, label, created_at,
                       expires_at, max_members):
        rows = self._post(
            "sessions",
            {
                "share_token": share_token,
                "owner_key": owner_key,
                "label": label,
                "created_at": created_at,
                "expires_at": expires_at,
                "max_members": max_members,
                "active": True,
            },
            return_rows=True,
        )
        return rows[0]["id"]

    def get_session(self, share_token):
        rows = self._get(
            "sessions",
            {"share_token": f"eq.{share_token}", "select": "*", "limit": 1},
        )
        return rows[0] if rows else None

    def stop_session(self, session_id):
        self._patch("sessions", {"id": f"eq.{session_id}"}, {"active": False})

    # -- members --------------------------------------------------------- #
    def count_members(self, session_id):
        rows = self._get(
            "members", {"session_id": f"eq.{session_id}", "select": "id"}
        )
        return len(rows)

    def add_member(self, session_id, member_token, name, joined_at):
        rows = self._post(
            "members",
            {
                "session_id": session_id,
                "member_token": member_token,
                "name": name,
                "joined_at": joined_at,
            },
            return_rows=True,
        )
        return rows[0]["id"]

    def get_member(self, session_id, member_token):
        rows = self._get(
            "members",
            {
                "session_id": f"eq.{session_id}",
                "member_token": f"eq.{member_token}",
                "select": "*",
                "limit": 1,
            },
        )
        return rows[0] if rows else None

    def list_members(self, session_id):
        return self._get(
            "members",
            {
                "session_id": f"eq.{session_id}",
                "select": "id,name,joined_at,last_seen",
                "order": "id.asc",
            },
        )

    def touch_member(self, member_id, last_seen):
        self._patch("members", {"id": f"eq.{member_id}"}, {"last_seen": last_seen})

    # -- locations ------------------------------------------------------- #
    def insert_location(self, session_id, member_id, lat, lng, accuracy,
                        client_ts, server_ts):
        self._post(
            "locations",
            {
                "session_id": session_id,
                "member_id": member_id,
                "lat": lat,
                "lng": lng,
                "accuracy": accuracy,
                "client_ts": client_ts,
                "server_ts": server_ts,
            },
        )

    def recent_locations(self, session_id, limit):
        return self._get(
            "locations",
            {
                "session_id": f"eq.{session_id}",
                "select": "id,member_id,lat,lng,accuracy,client_ts,server_ts",
                "order": "id.desc",
                "limit": limit,
            },
        )


def make_store(config: dict):
    """Pick a backend from config: Supabase if configured, else SQLite."""
    url = config.get("SUPABASE_URL")
    key = config.get("SUPABASE_SERVICE_KEY")
    if url and key:
        return SupabaseStore(url, key)
    return SQLiteStore()
