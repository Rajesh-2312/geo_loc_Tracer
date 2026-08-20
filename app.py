"""Consent-based web location tracer.

A creator generates a tracking link with a plain-language label describing who
is asking and why. When the recipient opens the link, the browser's Geolocation
API shows a native permission prompt; location is shared only if they allow it.
The creator watches incoming positions on a private, live-updating map.

There is deliberately no way to obtain a location without the recipient tapping
"Allow" in their own browser. Covert or IMEI-based tracking is not implemented.
"""

import io
import os
import secrets
from datetime import datetime, timedelta, timezone

import qrcode
import qrcode.image.svg
from dotenv import load_dotenv
from requests import RequestException
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    url_for,
)

import db
from store import make_store

# Load SUPABASE_URL / SUPABASE_SERVICE_KEY etc. from a local .env if present.
load_dotenv()

# Keep the newest N pings per session available to the dashboard.
MAX_LOCATIONS_RETURNED = 500
# Reject oversized ping bodies (a single coordinate reading is tiny).
MAX_PING_BYTES = 2_000
# Bound the requester label so the share page stays readable.
MAX_LABEL_LEN = 200
# Session lifetime bounds (minutes). A session auto-expires after this.
DEFAULT_EXPIRY_MINUTES = 24 * 60
MIN_EXPIRY_MINUTES = 5
MAX_EXPIRY_MINUTES = 7 * 24 * 60
# How many people (members) may join one link, and the allowed range.
DEFAULT_MAX_MEMBERS = 5
MIN_MAX_MEMBERS = 1
MAX_MAX_MEMBERS = 10
# Bound a member's display name.
MAX_NAME_LEN = 40
# Points of trail kept per member in the dashboard payload.
TRAIL_PER_MEMBER = 60


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat()


def is_expired(row) -> bool:
    """True once a session has passed its expires_at timestamp."""
    exp = row["expires_at"]
    if not exp:
        return False
    return utcnow() >= datetime.fromisoformat(exp)


def is_live(row) -> bool:
    """A session accepts location only while active and not yet expired."""
    return bool(row["active"]) and not is_expired(row)


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_PING_BYTES
    # Pick up Supabase credentials from the environment unless overridden.
    app.config.setdefault("SUPABASE_URL", os.environ.get("SUPABASE_URL"))
    app.config.setdefault("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_SERVICE_KEY"))
    if config:
        app.config.update(config)

    store = make_store(app.config)
    app.store = store

    db.init_app(app)
    # The local SQLite file is only needed for the SQLite backend.
    if store.backend == "sqlite":
        db.init_db(app)

    # ------------------------------------------------------------------ #
    # Error handling
    # ------------------------------------------------------------------ #
    @app.errorhandler(RequestException)
    def handle_storage_error(exc):
        # Raised when the Supabase backend is unreachable or misconfigured
        # (e.g. the tables have not been created yet).
        app.logger.error("Storage backend error: %s", exc)
        return (
            jsonify(
                error="Storage backend error. If using Supabase, make sure you "
                "ran supabase_schema.sql in the SQL Editor and that "
                "SUPABASE_URL / SUPABASE_SERVICE_KEY are correct."
            ),
            502,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def get_session_or_404(share_token: str):
        """Look up a session by its share token or abort with 404."""
        row = store.get_session(share_token)
        if row is None:
            abort(404)
        return row

    def require_owner(row) -> None:
        """Abort 403 unless the request carries this session's owner_key."""
        provided = request.args.get("key") or request.headers.get("X-Owner-Key")
        # Constant-time comparison avoids leaking the key via timing.
        if not provided or not secrets.compare_digest(provided, row["owner_key"]):
            abort(403)

    # ------------------------------------------------------------------ #
    # Pages
    # ------------------------------------------------------------------ #
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/t/<share_token>")
    def share_page(share_token: str):
        row = get_session_or_404(share_token)
        member_count = store.count_members(row["id"])
        max_members = row["max_members"]
        return render_template(
            "share.html",
            share_token=share_token,
            label=row["label"],
            active=is_live(row),
            expired=is_expired(row),
            expires_at=row["expires_at"],
            member_count=member_count,
            max_members=max_members,
            full=member_count >= max_members,
        )

    @app.get("/dashboard/<share_token>")
    def dashboard(share_token: str):
        row = get_session_or_404(share_token)
        require_owner(row)
        return render_template(
            "dashboard.html",
            share_token=share_token,
            label=row["label"],
            owner_key=row["owner_key"],
        )

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #
    @app.post("/api/sessions")
    def create_session():
        data = request.get_json(silent=True) or {}
        label = (data.get("label") or "").strip()
        if not label:
            return jsonify(error="A label describing the request is required."), 400
        label = label[:MAX_LABEL_LEN]

        # Clamp the requested lifetime to the allowed range.
        try:
            minutes = int(data.get("expiry_minutes", DEFAULT_EXPIRY_MINUTES))
        except (TypeError, ValueError):
            minutes = DEFAULT_EXPIRY_MINUTES
        minutes = max(MIN_EXPIRY_MINUTES, min(MAX_EXPIRY_MINUTES, minutes))
        expires_at = (utcnow() + timedelta(minutes=minutes)).isoformat()

        # Clamp the member cap to the allowed range.
        try:
            max_members = int(data.get("max_members", DEFAULT_MAX_MEMBERS))
        except (TypeError, ValueError):
            max_members = DEFAULT_MAX_MEMBERS
        max_members = max(MIN_MAX_MEMBERS, min(MAX_MAX_MEMBERS, max_members))

        share_token = secrets.token_urlsafe(9)
        owner_key = secrets.token_urlsafe(18)

        store.create_session(
            share_token, owner_key, label, utcnow_iso(), expires_at, max_members
        )

        share_url = url_for("share_page", share_token=share_token, _external=True)
        dashboard_url = url_for(
            "dashboard", share_token=share_token, key=owner_key, _external=True
        )
        qr_url = url_for("share_qr", share_token=share_token, _external=True)
        return jsonify(
            share_token=share_token,
            share_url=share_url,
            dashboard_url=dashboard_url,
            qr_url=qr_url,
            expires_at=expires_at,
            max_members=max_members,
        )

    @app.get("/t/<share_token>/qr.svg")
    def share_qr(share_token: str):
        get_session_or_404(share_token)
        share_url = url_for("share_page", share_token=share_token, _external=True)
        img = qrcode.make(
            share_url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12
        )
        buf = io.BytesIO()
        img.save(buf)
        return Response(buf.getvalue(), mimetype="image/svg+xml")

    @app.post("/api/sessions/<share_token>/join")
    def join(share_token: str):
        """A device joins the link as a member (subject to the member cap).

        Idempotent: a device that already holds a valid member_token gets the
        same membership back without consuming another slot.
        """
        row = get_session_or_404(share_token)
        if not is_live(row):
            reason = "expired" if is_expired(row) else "ended"
            return jsonify(error=f"This tracking session has {reason}."), 409

        data = request.get_json(silent=True) or {}

        # Returning member: reuse existing membership.
        existing_token = data.get("member_token")
        if existing_token:
            member = store.get_member(row["id"], existing_token)
            if member:
                return jsonify(
                    member_token=existing_token,
                    member_id=member["id"],
                    name=member["name"],
                    max_members=row["max_members"],
                    member_count=store.count_members(row["id"]),
                )

        # New member: enforce the cap.
        if store.count_members(row["id"]) >= row["max_members"]:
            return (
                jsonify(
                    error=f"This link is full ({row['max_members']} people have "
                    "already joined)."
                ),
                409,
            )

        name = (data.get("name") or "").strip()[:MAX_NAME_LEN] or "Guest"
        member_token = secrets.token_urlsafe(12)
        member_id = store.add_member(row["id"], member_token, name, utcnow_iso())
        return jsonify(
            member_token=member_token,
            member_id=member_id,
            name=name,
            max_members=row["max_members"],
            member_count=store.count_members(row["id"]),
        )

    @app.post("/api/sessions/<share_token>/ping")
    def ping(share_token: str):
        row = get_session_or_404(share_token)
        if not is_live(row):
            reason = "expired" if is_expired(row) else "ended"
            return jsonify(error=f"This tracking session has {reason}."), 409

        data = request.get_json(silent=True) or {}

        # A ping must come from a known member of this session.
        member_token = data.get("member_token")
        member = store.get_member(row["id"], member_token) if member_token else None
        if member is None:
            return jsonify(error="Unknown or missing member. Join first."), 403

        try:
            lat = float(data["lat"])
            lng = float(data["lng"])
        except (KeyError, TypeError, ValueError):
            return jsonify(error="lat and lng are required numbers."), 400

        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
            return jsonify(error="Coordinates out of range."), 400

        accuracy = data.get("accuracy")
        try:
            accuracy = float(accuracy) if accuracy is not None else None
        except (TypeError, ValueError):
            accuracy = None

        client_ts = data.get("client_ts")
        if client_ts is not None:
            client_ts = str(client_ts)[:64]

        now = utcnow_iso()
        store.insert_location(
            row["id"], member["id"], lat, lng, accuracy, client_ts, now
        )
        store.touch_member(member["id"], now)
        return jsonify(ok=True)

    @app.post("/api/sessions/<share_token>/stop")
    def stop(share_token: str):
        row = get_session_or_404(share_token)
        store.stop_session(row["id"])
        return jsonify(ok=True)

    @app.get("/api/sessions/<share_token>/locations")
    def locations(share_token: str):
        row = get_session_or_404(share_token)
        require_owner(row)

        members = store.list_members(row["id"])
        recent = store.recent_locations(row["id"], MAX_LOCATIONS_RETURNED)
        # recent is newest-first; group by member and keep a bounded trail.
        by_member: dict = {}
        for loc in recent:
            by_member.setdefault(loc["member_id"], []).append(loc)

        member_views = []
        for m in members:
            pts = by_member.get(m["id"], [])  # newest-first
            trail = list(reversed(pts[:TRAIL_PER_MEMBER]))  # oldest-first for drawing
            latest = pts[0] if pts else None
            member_views.append(
                {
                    "id": m["id"],
                    "name": m["name"],
                    "joined_at": m["joined_at"],
                    "last_seen": m["last_seen"],
                    "latest": latest,
                    "trail": [[p["lat"], p["lng"]] for p in trail],
                }
            )

        return jsonify(
            active=is_live(row),
            expired=is_expired(row),
            expires_at=row["expires_at"],
            label=row["label"],
            max_members=row["max_members"],
            member_count=len(members),
            members=member_views,
        )

    return app


app = create_app()


if __name__ == "__main__":
    # Bind to all interfaces so a phone on the same Wi-Fi can reach the share
    # link. Geolocation requires HTTPS on non-localhost origins (see README).
    app.run(host="0.0.0.0", port=5000, debug=True)
