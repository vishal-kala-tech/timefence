import sqlite3
from pathlib import Path
from typing import List, Optional

from ..models.usage import DailyUsage, SessionRecord
from .usage_store import UsageStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_usage (
    usage_date TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    total_active_seconds INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (usage_date, resource_id)
);

CREATE TABLE IF NOT EXISTS usage_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER DEFAULT 0,
    activity_kind TEXT NOT NULL DEFAULT 'app',
    identifier TEXT
);

CREATE TABLE IF NOT EXISTS warning_state (
    usage_date TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    warning_key TEXT NOT NULL,
    PRIMARY KEY (usage_date, resource_id, warning_key)
);

CREATE INDEX IF NOT EXISTS usage_sessions_open_idx
    ON usage_sessions (resource_id, ended_at);
"""


def _row_daily(row) -> DailyUsage:
    return DailyUsage(
        resource_id=row["resource_id"],
        date=row["usage_date"],
        total_active_seconds=int(row["total_active_seconds"] or 0),
        updated_at=row["updated_at"],
    )


def _row_session(row) -> SessionRecord:
    return SessionRecord(
        id=int(row["id"]),
        resource_id=row["resource_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration_seconds=int(row["duration_seconds"] or 0),
        activity_kind=row["activity_kind"] or "app",
        identifier=row["identifier"] or "",
    )


class SqliteUsageStore(UsageStore):
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def add_active_seconds(self, usage_date: str, resource_id: str, seconds: int, updated_at: str) -> int:
        seconds = max(0, int(seconds or 0))
        with self._connect() as conn:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO daily_usage (usage_date, resource_id, total_active_seconds, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(usage_date, resource_id) DO UPDATE SET
                    total_active_seconds = total_active_seconds + excluded.total_active_seconds,
                    updated_at = excluded.updated_at
                """,
                (usage_date, resource_id, seconds, updated_at),
            )
            row = conn.execute(
                "SELECT total_active_seconds FROM daily_usage WHERE usage_date = ? AND resource_id = ?",
                (usage_date, resource_id),
            ).fetchone()
            conn.commit()
        return int(row["total_active_seconds"] if row else seconds)

    def get_daily(self, usage_date: str, resource_id: str) -> Optional[DailyUsage]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM daily_usage WHERE usage_date = ? AND resource_id = ?",
                (usage_date, resource_id),
            ).fetchone()
        return _row_daily(row) if row else None

    def get_all_daily(self, usage_date: str) -> List[DailyUsage]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM daily_usage WHERE usage_date = ? ORDER BY resource_id",
                (usage_date,),
            ).fetchall()
        return [_row_daily(row) for row in rows]

    def start_session(
        self,
        resource_id: str,
        started_at: str,
        activity_kind: str = "app",
        identifier: str = "",
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO usage_sessions (resource_id, started_at, duration_seconds, activity_kind, identifier)
                VALUES (?, ?, 0, ?, ?)
                """,
                (resource_id, started_at, activity_kind or "app", identifier or ""),
            )
            return int(cursor.lastrowid)

    def update_session(self, session_id: int, duration_seconds: int, ended_at: Optional[str] = None) -> None:
        with self._connect() as conn:
            if ended_at is None:
                conn.execute(
                    "UPDATE usage_sessions SET duration_seconds = ? WHERE id = ?",
                    (int(duration_seconds or 0), session_id),
                )
            else:
                conn.execute(
                    "UPDATE usage_sessions SET duration_seconds = ?, ended_at = ? WHERE id = ?",
                    (int(duration_seconds or 0), ended_at, session_id),
                )

    def end_session(self, session_id: int, ended_at: str, duration_seconds: int) -> None:
        self.update_session(session_id, duration_seconds, ended_at=ended_at)

    def get_open_session(self, resource_id: str) -> Optional[SessionRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM usage_sessions
                WHERE resource_id = ? AND ended_at IS NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (resource_id,),
            ).fetchone()
        return _row_session(row) if row else None

    def get_open_sessions(self) -> List[SessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM usage_sessions WHERE ended_at IS NULL ORDER BY id"
            ).fetchall()
        return [_row_session(row) for row in rows]

    def record_warning(self, usage_date: str, resource_id: str, warning_key: str) -> bool:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO warning_state (usage_date, resource_id, warning_key) VALUES (?, ?, ?)",
                    (usage_date, resource_id, warning_key),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def has_warning(self, usage_date: str, resource_id: str, warning_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM warning_state
                WHERE usage_date = ? AND resource_id = ? AND warning_key = ?
                """,
                (usage_date, resource_id, warning_key),
            ).fetchone()
        return row is not None
