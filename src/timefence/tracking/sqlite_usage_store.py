"""SQLite implementation of UsageStore (`state/screen_time.sqlite`).

Canonical store for daily totals, per-window totals, sessions, browser visits,
and YouTube watches. `rules.json` still defines the windows (ids, hours, limits).
JSON files under `state/<resource>/` keep warning keys and a cache of the rest;
legacy JSON counters/visits are used only if SQLite has no row yet.
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

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

CREATE TABLE IF NOT EXISTS window_usage (
    usage_date TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    window_id TEXT NOT NULL,
    usage_seconds INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (usage_date, resource_id, window_id)
);

CREATE TABLE IF NOT EXISTS browse_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_date TEXT NOT NULL,
    host TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    usage_seconds INTEGER NOT NULL DEFAULT 0,
    browser TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS watch_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_date TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    usage_seconds INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS usage_sessions_open_idx
    ON usage_sessions (resource_id, ended_at);
CREATE INDEX IF NOT EXISTS browse_visits_date_idx
    ON browse_visits (usage_date, id);
CREATE INDEX IF NOT EXISTS watch_history_date_idx
    ON watch_history (usage_date, resource_id, id);
"""

MAX_BROWSE_VISITS = 5000
MAX_WATCHES = 5000


def _row_daily(row) -> DailyUsage:
    return DailyUsage(
        resource_id=row["resource_id"],
        date=row["usage_date"],
        total_active_seconds=int(row["total_active_seconds"] or 0),
        updated_at=row["updated_at"],
    )


def _row_visit(row) -> dict:
    entry = {
        "host": row["host"] or "",
        "url": row["url"] or "",
        "title": row["title"] or "",
        "first_seen": row["first_seen"] or "",
        "last_seen": row["last_seen"] or "",
        "usage_seconds": int(row["usage_seconds"] or 0),
    }
    browser = str(row["browser"] or "").strip()
    if browser:
        entry["browser"] = browser
    return entry


def _row_watch(row) -> dict:
    return {
        "id": row["video_id"] or "",
        "title": row["title"] or "",
        "channel": row["channel"] or "",
        "url": row["url"] or "",
        "first_seen": row["first_seen"] or "",
        "last_seen": row["last_seen"] or "",
        "usage_seconds": int(row["usage_seconds"] or 0),
    }


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
        """Atomically upsert the day's total. Returns the new total."""
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

    def add_window_seconds(
        self, usage_date: str, resource_id: str, window_id: str, seconds: int, updated_at: str
    ) -> int:
        seconds = max(0, int(seconds or 0))
        window_id = str(window_id or "").strip()
        if not window_id:
            return 0
        with self._connect() as conn:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO window_usage (usage_date, resource_id, window_id, usage_seconds, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(usage_date, resource_id, window_id) DO UPDATE SET
                    usage_seconds = usage_seconds + excluded.usage_seconds,
                    updated_at = excluded.updated_at
                """,
                (usage_date, resource_id, window_id, seconds, updated_at),
            )
            row = conn.execute(
                """
                SELECT usage_seconds FROM window_usage
                WHERE usage_date = ? AND resource_id = ? AND window_id = ?
                """,
                (usage_date, resource_id, window_id),
            ).fetchone()
            conn.commit()
        return int(row["usage_seconds"] if row else seconds)

    def get_windows(self, usage_date: str, resource_id: str) -> Dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT window_id, usage_seconds FROM window_usage
                WHERE usage_date = ? AND resource_id = ?
                ORDER BY window_id
                """,
                (usage_date, resource_id),
            ).fetchall()
        return {str(row["window_id"]): int(row["usage_seconds"] or 0) for row in rows}

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
                # Already recorded today; the controller uses the False return to skip a second log line.
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

    def get_browse_visits(self, usage_date: str) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM browse_visits WHERE usage_date = ? ORDER BY id",
                (usage_date,),
            ).fetchall()
        return [_row_visit(row) for row in rows]

    def seed_browse_visits(self, usage_date: str, visits) -> None:
        if self.get_browse_visits(usage_date):
            return
        with self._connect() as conn:
            for visit in visits or []:
                url = str((visit or {}).get("url") or "").strip()
                host = str((visit or {}).get("host") or "").strip()
                if not url or not host:
                    continue
                conn.execute(
                    """
                    INSERT INTO browse_visits (
                        usage_date, host, url, title, first_seen, last_seen, usage_seconds, browser
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        usage_date,
                        host,
                        url,
                        str((visit or {}).get("title") or ""),
                        str((visit or {}).get("first_seen") or ""),
                        str((visit or {}).get("last_seen") or ""),
                        max(0, int((visit or {}).get("usage_seconds") or 0)),
                        str((visit or {}).get("browser") or ""),
                    ),
                )
            conn.commit()

    def add_browse_visit(
        self,
        usage_date: str,
        host: str,
        url: str,
        title: str,
        seconds: int,
        seen_at: str,
        browser: str = "",
        max_rows: int = MAX_BROWSE_VISITS,
    ) -> str:
        host = str(host or "").strip()
        url = str(url or "").strip()
        if not host or not url:
            return "skipped"
        title = str(title or "")
        browser = str(browser or "").strip()
        seconds = max(0, int(seconds or 0))
        with self._connect() as conn:
            last = conn.execute(
                "SELECT * FROM browse_visits WHERE usage_date = ? ORDER BY id DESC LIMIT 1",
                (usage_date,),
            ).fetchone()
            if last and last["url"] == url:
                conn.execute(
                    """
                    UPDATE browse_visits
                    SET last_seen = ?,
                        usage_seconds = usage_seconds + ?,
                        title = CASE WHEN ? != '' THEN ? ELSE title END,
                        host = CASE WHEN ? != '' THEN ? ELSE host END,
                        browser = CASE WHEN ? != '' THEN ? ELSE browser END
                    WHERE id = ?
                    """,
                    (seen_at, seconds, title, title, host, host, browser, browser, last["id"]),
                )
                conn.commit()
                return "updated"
            count = conn.execute(
                "SELECT COUNT(*) FROM browse_visits WHERE usage_date = ?",
                (usage_date,),
            ).fetchone()[0]
            if int(count) >= int(max_rows):
                return "full"
            conn.execute(
                """
                INSERT INTO browse_visits (
                    usage_date, host, url, title, first_seen, last_seen, usage_seconds, browser
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (usage_date, host, url, title, seen_at, seen_at, seconds, browser),
            )
            conn.commit()
        return "inserted"

    def get_watches(self, usage_date: str, resource_id: str) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM watch_history
                WHERE usage_date = ? AND resource_id = ?
                ORDER BY id
                """,
                (usage_date, resource_id),
            ).fetchall()
        return [_row_watch(row) for row in rows]

    def seed_watches(self, usage_date: str, resource_id: str, videos) -> None:
        if self.get_watches(usage_date, resource_id):
            return
        with self._connect() as conn:
            for video in videos or []:
                video_id = str((video or {}).get("id") or "").strip()
                if not video_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO watch_history (
                        usage_date, resource_id, video_id, title, channel, url,
                        first_seen, last_seen, usage_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        usage_date,
                        resource_id,
                        video_id,
                        str((video or {}).get("title") or ""),
                        str((video or {}).get("channel") or ""),
                        str((video or {}).get("url") or ""),
                        str((video or {}).get("first_seen") or ""),
                        str((video or {}).get("last_seen") or ""),
                        max(0, int((video or {}).get("usage_seconds") or 0)),
                    ),
                )
            conn.commit()

    def add_watch(
        self,
        usage_date: str,
        resource_id: str,
        video: dict,
        seconds: int,
        seen_at: str,
        max_rows: int = MAX_WATCHES,
    ) -> str:
        if not isinstance(video, dict):
            return "skipped"
        video_id = str(video.get("id") or "").strip()
        if not video_id:
            return "skipped"
        title = str(video.get("title") or "")
        channel = str(video.get("channel") or "")
        url = str(video.get("url") or "")
        seconds = max(0, int(seconds or 0))
        with self._connect() as conn:
            last = conn.execute(
                """
                SELECT * FROM watch_history
                WHERE usage_date = ? AND resource_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (usage_date, resource_id),
            ).fetchone()
            if last and last["video_id"] == video_id:
                conn.execute(
                    """
                    UPDATE watch_history
                    SET last_seen = ?,
                        usage_seconds = usage_seconds + ?,
                        title = CASE WHEN ? != '' THEN ? ELSE title END,
                        channel = CASE WHEN ? != '' THEN ? ELSE channel END,
                        url = CASE WHEN ? != '' THEN ? ELSE url END
                    WHERE id = ?
                    """,
                    (seen_at, seconds, title, title, channel, channel, url, url, last["id"]),
                )
                conn.commit()
                return "updated"
            count = conn.execute(
                "SELECT COUNT(*) FROM watch_history WHERE usage_date = ? AND resource_id = ?",
                (usage_date, resource_id),
            ).fetchone()[0]
            if int(count) >= int(max_rows):
                return "full"
            conn.execute(
                """
                INSERT INTO watch_history (
                    usage_date, resource_id, video_id, title, channel, url,
                    first_seen, last_seen, usage_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (usage_date, resource_id, video_id, title, channel, url, seen_at, seen_at, seconds),
            )
            conn.commit()
        return "inserted"
