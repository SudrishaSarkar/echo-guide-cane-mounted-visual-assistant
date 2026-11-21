"""SQLite storage: event history and the care profile (Person 3).

One shared connection guarded by a lock, because the serial thread, background
workers and FastAPI's thread pool all write to it. The file defaults to
backend/echoguide.db (gitignored); set "db_path" in settings.json to move it.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from .hooks import BACKEND_DIR, setting

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    type          TEXT NOT NULL,
    payload       TEXT NOT NULL DEFAULT '{}',
    notify_status TEXT NOT NULL DEFAULT 'not_sent'
);
CREATE INDEX IF NOT EXISTS events_type ON events(type);
CREATE TABLE IF NOT EXISTS profile (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

NOTIFY_STATUSES = {"pending", "delivered", "not_sent"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _event_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "ts": row["ts"],
        "type": row["type"],
        "payload": json.loads(row["payload"]),
        "notify_status": row["notify_status"],
    }


class Database:
    def __init__(self, path: Union[str, Path]) -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # Events -------------------------------------------------------------

    def add_event(
        self,
        type: str,
        payload: Optional[dict] = None,
        notify_status: str = "not_sent",
        ts: Optional[str] = None,
    ) -> dict:
        if notify_status not in NOTIFY_STATUSES:
            raise ValueError(f"bad notify_status {notify_status!r}")
        ts = ts or utc_now_iso()
        body = json.dumps(payload or {}, default=str)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events (ts, type, payload, notify_status) VALUES (?, ?, ?, ?)",
                (ts, type, body, notify_status),
            )
            self._conn.commit()
            event_id = cur.lastrowid
        return {
            "id": event_id,
            "ts": ts,
            "type": type,
            "payload": json.loads(body),
            "notify_status": notify_status,
        }

    def update_event(self, event_id: int, *, notify_status: str) -> Optional[dict]:
        if notify_status not in NOTIFY_STATUSES:
            raise ValueError(f"bad notify_status {notify_status!r}")
        with self._lock:
            self._conn.execute(
                "UPDATE events SET notify_status = ? WHERE id = ?", (notify_status, event_id)
            )
            self._conn.commit()
        return self.get_event(event_id)

    def get_event(self, event_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return _event_from_row(row) if row else None

    def list_events(self, limit: int = 50) -> list[dict]:
        """Newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_event_from_row(r) for r in rows]

    # Profile ------------------------------------------------------------

    def get_profile(self) -> Optional[dict]:
        """{"data": {...}, "updated_at": iso} or None if never set."""
        with self._lock:
            row = self._conn.execute("SELECT data, updated_at FROM profile WHERE id = 1").fetchone()
        if row is None:
            return None
        return {"data": json.loads(row["data"]), "updated_at": row["updated_at"]}

    def set_profile(self, data: dict) -> str:
        updated_at = utc_now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO profile (id, data, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                (json.dumps(data), updated_at),
            )
            self._conn.commit()
        return updated_at

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_db: Optional[Database] = None
_db_lock = threading.Lock()


def get_db() -> Database:
    global _db
    with _db_lock:
        if _db is None:
            _db = Database(setting("db_path") or BACKEND_DIR / "echoguide.db")
        return _db


def set_db(db: Optional[Database]) -> None:
    """Swap the shared database (tests use an in-memory one)."""
    global _db
    with _db_lock:
        _db = db
