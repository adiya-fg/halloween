"""SQLite access layer.

All queries use parameter binding (never string formatting with user data),
which prevents SQL injection. State-changing operations that must be atomic
use ``BEGIN IMMEDIATE`` transactions to take SQLite's write lock up front.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator

STATUSES = ("PENDING_PAYMENT", "PAYMENT_REPORTED", "APPROVED", "REJECTED", "EXPIRED")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS admins (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    last_login_at  TEXT
);

CREATE TABLE IF NOT EXISTS admin_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash  TEXT NOT NULL UNIQUE,
    admin_id    INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    csrf_token  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sticker_requests (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    request_code           TEXT NOT NULL UNIQUE,
    tracking_token_hash    TEXT NOT NULL UNIQUE,
    idempotency_key_hash   TEXT UNIQUE,
    client_ip_hash         TEXT,
    name                   TEXT NOT NULL,
    email                  TEXT,
    template_id            TEXT,
    character              TEXT,              -- quiz result (computed server-side)
    amount                 INTEGER NOT NULL CHECK (amount > 0),   -- minor units
    currency               TEXT NOT NULL CHECK (length(currency) = 3),
    status                 TEXT NOT NULL CHECK (status IN ({", ".join(f"'{s}'" for s in STATUSES)})),
    payment_reported_at    TEXT,
    approved_at            TEXT,
    rejected_at            TEXT,
    rejection_reason       TEXT,
    admin_notes            TEXT,
    transaction_reference  TEXT,
    approved_by            INTEGER REFERENCES admins(id),
    rejected_by            INTEGER REFERENCES admins(id),
    expires_at             TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requests_status ON sticker_requests(status);
CREATE INDEX IF NOT EXISTS idx_requests_ip ON sticker_requests(client_ip_hash, created_at);

CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    actor_type  TEXT NOT NULL,      -- admin | user | system | anonymous
    actor_id    INTEGER,
    action      TEXT NOT NULL,
    target      TEXT,
    details     TEXT,
    ip_hash     TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);

-- Privacy-friendly aggregate analytics: daily counts only, no per-user rows.
CREATE TABLE IF NOT EXISTS analytics_counters (
    event  TEXT NOT NULL,
    day    TEXT NOT NULL,
    count  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (event, day)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ts(dt: datetime | None = None) -> str:
    """Fixed-width ISO-8601 UTC timestamp (sortable as text)."""
    return (dt or utcnow()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ts_plus(**kwargs) -> str:
    return ts(utcnow() + timedelta(**kwargs))


class Database:
    def __init__(self, path: str):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = self.connect()
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Exclusive-write transaction; commits on success, rolls back on error."""
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")
        finally:
            c.close()

    def init_schema(self) -> None:
        with self.conn() as c:
            c.execute("PRAGMA journal_mode = WAL")
            c.executescript(SCHEMA)
            # Lightweight migrations for databases created by earlier versions.
            cols = {r["name"] for r in c.execute("PRAGMA table_info(sticker_requests)")}
            if "character" not in cols:
                c.execute("ALTER TABLE sticker_requests ADD COLUMN character TEXT")
