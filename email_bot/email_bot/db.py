"""SQLite persistence layer.

Tables
------
campaigns        – campaign metadata
recipients       – imported recipient rows (per-campaign)
send_log         – one row per send attempt (idempotency + reporting)
campaign_markers – boolean markers such as "dry_run_completed"
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from email_bot.config import DB_FILE

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS campaigns (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    template_dir  TEXT NOT NULL,
    sender_name   TEXT NOT NULL DEFAULT '',
    signature     TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recipients (
    rowid         INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id   TEXT NOT NULL REFERENCES campaigns(id),
    email         TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT 'there',
    extra_json    TEXT NOT NULL DEFAULT '{}',
    imported_at   TEXT NOT NULL,
    UNIQUE(campaign_id, email)
);

CREATE TABLE IF NOT EXISTS send_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id     TEXT NOT NULL REFERENCES campaigns(id),
    recipient_email TEXT NOT NULL,
    template_hash   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    gmail_message_id TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_send_log
    ON send_log(campaign_id, recipient_email, template_hash);

CREATE TABLE IF NOT EXISTS campaign_markers (
    campaign_id   TEXT NOT NULL REFERENCES campaigns(id),
    marker        TEXT NOT NULL,
    value         TEXT NOT NULL DEFAULT '1',
    created_at    TEXT NOT NULL,
    PRIMARY KEY (campaign_id, marker)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thin wrapper around a SQLite connection with helpers for each table."""

    def __init__(self, db_path: Path = DB_FILE) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_CREATE_SQL)
        self.conn.commit()

    # ── campaigns ────────────────────────────────────────────────────────

    def create_campaign(
        self,
        campaign_id: str,
        name: str,
        template_dir: str,
        sender_name: str = "",
        signature: str = "",
    ) -> None:
        self.conn.execute(
            "INSERT INTO campaigns (id, name, template_dir, sender_name, signature, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (campaign_id, name, template_dir, sender_name, signature, _now()),
        )
        self.conn.commit()

    def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_campaigns(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    # ── recipients ───────────────────────────────────────────────────────

    def upsert_recipient(
        self,
        campaign_id: str,
        email: str,
        name: str,
        extra_json: str,
    ) -> bool:
        """Insert or ignore a recipient. Returns True if a new row was created."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO recipients (campaign_id, email, name, extra_json, imported_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (campaign_id, email, name, extra_json, _now()),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_recipients(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM recipients WHERE campaign_id = ? ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def recipient_count(self, campaign_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM recipients WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        return row["cnt"]

    # ── send_log ─────────────────────────────────────────────────────────

    def already_sent(self, campaign_id: str, email: str, tpl_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT status FROM send_log "
            "WHERE campaign_id = ? AND recipient_email = ? AND template_hash = ?",
            (campaign_id, email, tpl_hash),
        ).fetchone()
        return row is not None and row["status"] == "sent"

    def log_attempt(
        self,
        campaign_id: str,
        email: str,
        tpl_hash: str,
        status: str = "pending",
        gmail_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        now = _now()
        self.conn.execute(
            "INSERT INTO send_log "
            "(campaign_id, recipient_email, template_hash, status, gmail_message_id, error, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(campaign_id, recipient_email, template_hash) DO UPDATE SET "
            "status=excluded.status, gmail_message_id=excluded.gmail_message_id, "
            "error=excluded.error, updated_at=excluded.updated_at",
            (campaign_id, email, tpl_hash, status, gmail_message_id, error, now, now),
        )
        self.conn.commit()

    def get_send_log(self, campaign_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM send_log WHERE campaign_id = ? ORDER BY id", (campaign_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def campaign_send_stats(self, campaign_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM send_log WHERE campaign_id = ? GROUP BY status",
            (campaign_id,),
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    # ── markers ──────────────────────────────────────────────────────────

    def set_marker(self, campaign_id: str, marker: str, value: str = "1") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO campaign_markers (campaign_id, marker, value, created_at) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, marker, value, _now()),
        )
        self.conn.commit()

    def get_marker(self, campaign_id: str, marker: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM campaign_markers WHERE campaign_id = ? AND marker = ?",
            (campaign_id, marker),
        ).fetchone()
        return row["value"] if row else None

    def close(self) -> None:
        self.conn.close()
