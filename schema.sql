-- Consent-based location tracer schema (SQLite).

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    share_token  TEXT NOT NULL UNIQUE,
    owner_key    TEXT NOT NULL,
    label        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT,
    max_members  INTEGER NOT NULL DEFAULT 5,
    active       INTEGER NOT NULL DEFAULT 1
);

-- Each device that joins a link becomes a member. A session allows up to
-- max_members of them; every location ping belongs to one member.
CREATE TABLE IF NOT EXISTS members (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL,
    member_token  TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    joined_at     TEXT NOT NULL,
    last_seen     TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL,
    member_id   INTEGER,
    lat         REAL NOT NULL,
    lng         REAL NOT NULL,
    accuracy    REAL,
    client_ts   TEXT,
    server_ts   TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE,
    FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_locations_session
    ON locations (session_id, id);
CREATE INDEX IF NOT EXISTS idx_members_session
    ON members (session_id);
