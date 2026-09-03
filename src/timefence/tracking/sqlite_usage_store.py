"""SQLite implementation of UsageStore (`state/screen_time.sqlite`).

Canonical store for resources, daily totals, per-window totals, sessions,
browser visits, and video watches. Every usage row is keyed by
(resource_type, resource_id). App totals are screen time; website and
video_category totals attribute the same foreground interval and must not be
added together.
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..identity import (
    RESOURCE_TYPE_VIDEO_CATEGORY,
    RESOURCE_TYPE_WEBSITE,
    default_display_name,
    identifier_type_for,
    website_id,
)
from ..models.usage import DailyUsage, SessionRecord
from .usage_store import UsageStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    identifier_type TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (resource_type, resource_id)
);

CREATE TABLE IF NOT EXISTS daily_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_date TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    total_active_seconds INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE (usage_date, resource_type, resource_id)
);

CREATE TABLE IF NOT EXISTS usage_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    pid INTEGER,
    identifier TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS warning_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_date TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    warning_key TEXT NOT NULL,
    triggered_at TEXT,
    UNIQUE (usage_date, resource_type, resource_id, warning_key)
);

CREATE TABLE IF NOT EXISTS window_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_date TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    window_id TEXT NOT NULL,
    usage_seconds INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE (usage_date, resource_type, resource_id, window_id)
);

CREATE TABLE IF NOT EXISTS browse_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_date TEXT NOT NULL,
    resource_type TEXT NOT NULL DEFAULT 'website',
    resource_id TEXT NOT NULL,
    host TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    browser_resource_id TEXT,
    browser_name TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    usage_seconds INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS watch_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_date TEXT NOT NULL,
    resource_type TEXT NOT NULL DEFAULT 'video_category',
    resource_id TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'youtube',
    video_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    usage_seconds INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS usage_sessions_open_idx
ON usage_sessions (
    resource_type,
    resource_id,
    ended_at
);

CREATE INDEX IF NOT EXISTS usage_sessions_started_idx
ON usage_sessions (
    started_at
);

CREATE INDEX IF NOT EXISTS browse_visits_date_idx
ON browse_visits (
    usage_date,
    id
);

CREATE INDEX IF NOT EXISTS browse_visits_resource_date_idx
ON browse_visits (
    usage_date,
    resource_id
);

CREATE INDEX IF NOT EXISTS watch_history_date_idx
ON watch_history (
    usage_date,
    resource_type,
    resource_id,
    id
);
"""

MAX_BROWSE_VISITS = 5000
MAX_WATCHES = 5000


def _row_resource(row) -> dict:
    return {
        "id": int(row["id"]),
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
        "display_name": row["display_name"] or "",
        "identifier_type": row["identifier_type"] or "",
        "metadata_json": row["metadata_json"] or "{}",
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
    }


def _row_daily(row) -> DailyUsage:
    return DailyUsage(
        id=int(row["id"]),
        resource_type=row["resource_type"],
        resource_id=row["resource_id"],
        date=row["usage_date"],
        total_active_seconds=int(row["total_active_seconds"] or 0),
        updated_at=row["updated_at"] or "",
    )


def _row_session(row) -> SessionRecord:
    pid = row["pid"]
    return SessionRecord(
        id=int(row["id"]),
        resource_type=row["resource_type"],
        resource_id=row["resource_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration_seconds=int(row["duration_seconds"] or 0),
        pid=int(pid) if pid is not None else None,
        identifier=row["identifier"] or "",
        created_at=row["created_at"] or "",
    )


def _row_visit(row) -> dict:
    return {
        "id": int(row["id"]),
        "usage_date": row["usage_date"],
        "resource_type": row["resource_type"] or RESOURCE_TYPE_WEBSITE,
        "resource_id": row["resource_id"],
        "host": row["host"],
        "url": row["url"],
        "title": row["title"] or "",
        "browser_resource_id": row["browser_resource_id"] or "",
        "browser_name": row["browser_name"] or "",
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "usage_seconds": int(row["usage_seconds"] or 0),
    }


def _row_watch(row) -> dict:
    video_id = row["video_id"]
    return {
        "id": video_id,
        "usage_date": row["usage_date"],
        "resource_type": row["resource_type"] or RESOURCE_TYPE_VIDEO_CATEGORY,
        "resource_id": row["resource_id"],
        "platform": row["platform"] or "youtube",
        "video_id": video_id,
        "title": row["title"] or "",
        "channel": row["channel"] or "",
        "url": row["url"] or "",
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "usage_seconds": int(row["usage_seconds"] or 0),
    }


def _better_display_name(current, incoming, resource_id):
    incoming = str(incoming or "").strip()
    current = str(current or "").strip()
    if not incoming:
        return current
    if not current or current == resource_id:
        return incoming
    if incoming == resource_id:
        return current
    return incoming


class SqliteUsageStore(UsageStore):
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._reset_if_stale()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _reset_if_stale(self):
        """New product schema: recreate the file if an old table shape is present."""
        if not self.path.exists():
            return
        with self._connect() as conn:
            resources = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='resources'"
            ).fetchone()
            resource_cols = [row[1] for row in conn.execute("PRAGMA table_info(resources)").fetchall()]
            daily_cols = [row[1] for row in conn.execute("PRAGMA table_info(daily_usage)").fetchall()]
        if resources is None or "id" not in resource_cols or "id" not in daily_cols:
            self.path.unlink()

    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def ensure_resource(
        self,
        resource_type: str,
        resource_id: str,
        display_name: str = "",
        identifier_type: str = "",
        metadata_json: Optional[str] = None,
        updated_at: str = "",
    ) -> dict:
        resource_type = str(resource_type or "").strip()
        resource_id = str(resource_id or "").strip()
        if not resource_type or not resource_id:
            return {}
        display_name = str(display_name or "").strip() or default_display_name(resource_type, resource_id)
        identifier_type = str(identifier_type or "").strip() or identifier_type_for(resource_type)
        updated_at = str(updated_at or "").strip()
        incoming_meta = metadata_json
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM resources
                WHERE resource_type = ? AND resource_id = ?
                """,
                (resource_type, resource_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO resources (
                        resource_type, resource_id, display_name, identifier_type,
                        metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resource_type,
                        resource_id,
                        display_name,
                        identifier_type,
                        incoming_meta if incoming_meta is not None else "{}",
                        updated_at,
                        updated_at,
                    ),
                )
            else:
                name = _better_display_name(row["display_name"], display_name, resource_id)
                ident = identifier_type or row["identifier_type"] or identifier_type_for(resource_type)
                meta = incoming_meta if incoming_meta is not None else (row["metadata_json"] or "{}")
                if incoming_meta is not None and row["metadata_json"] and row["metadata_json"] != "{}":
                    try:
                        merged = json.loads(row["metadata_json"])
                        if isinstance(merged, dict):
                            extra = json.loads(incoming_meta) if incoming_meta else {}
                            if isinstance(extra, dict):
                                merged.update(extra)
                                meta = json.dumps(merged, separators=(",", ":"))
                    except (TypeError, ValueError):
                        meta = incoming_meta
                conn.execute(
                    """
                    UPDATE resources
                    SET display_name = ?, identifier_type = ?, metadata_json = ?, updated_at = ?
                    WHERE resource_type = ? AND resource_id = ?
                    """,
                    (name, ident, meta, updated_at, resource_type, resource_id),
                )
            row = conn.execute(
                """
                SELECT * FROM resources
                WHERE resource_type = ? AND resource_id = ?
                """,
                (resource_type, resource_id),
            ).fetchone()
        return _row_resource(row) if row else {}

    def get_resource(self, resource_type: str, resource_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM resources
                WHERE resource_type = ? AND resource_id = ?
                """,
                (resource_type, resource_id),
            ).fetchone()
        return _row_resource(row) if row else None

    def list_resources(self, resource_type: Optional[str] = None) -> List[dict]:
        with self._connect() as conn:
            if resource_type:
                rows = conn.execute(
                    """
                    SELECT * FROM resources
                    WHERE resource_type = ?
                    ORDER BY display_name COLLATE NOCASE, resource_id
                    """,
                    (resource_type,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM resources
                    ORDER BY resource_type, display_name COLLATE NOCASE, resource_id
                    """
                ).fetchall()
        return [_row_resource(row) for row in rows]

    def add_active_seconds(
        self,
        usage_date: str,
        resource_type: str,
        resource_id: str,
        seconds: int,
        updated_at: str,
    ) -> int:
        seconds = max(0, int(seconds or 0))
        with self._connect() as conn:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO daily_usage (
                    usage_date, resource_type, resource_id, total_active_seconds, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(usage_date, resource_type, resource_id) DO UPDATE SET
                    total_active_seconds = total_active_seconds + excluded.total_active_seconds,
                    updated_at = excluded.updated_at
                """,
                (usage_date, resource_type, resource_id, seconds, updated_at),
            )
            row = conn.execute(
                """
                SELECT total_active_seconds FROM daily_usage
                WHERE usage_date = ? AND resource_type = ? AND resource_id = ?
                """,
                (usage_date, resource_type, resource_id),
            ).fetchone()
            conn.commit()
        return int(row["total_active_seconds"] if row else seconds)

    def get_daily(self, usage_date: str, resource_type: str, resource_id: str) -> Optional[DailyUsage]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM daily_usage
                WHERE usage_date = ? AND resource_type = ? AND resource_id = ?
                """,
                (usage_date, resource_type, resource_id),
            ).fetchone()
        return _row_daily(row) if row else None

    def get_all_daily(self, usage_date: str, resource_type: Optional[str] = None) -> List[DailyUsage]:
        with self._connect() as conn:
            if resource_type:
                rows = conn.execute(
                    """
                    SELECT * FROM daily_usage
                    WHERE usage_date = ? AND resource_type = ?
                    ORDER BY resource_id
                    """,
                    (usage_date, resource_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM daily_usage
                    WHERE usage_date = ?
                    ORDER BY resource_type, resource_id
                    """,
                    (usage_date,),
                ).fetchall()
        return [_row_daily(row) for row in rows]

    def add_window_seconds(
        self,
        usage_date: str,
        resource_type: str,
        resource_id: str,
        window_id: str,
        seconds: int,
        updated_at: str,
    ) -> int:
        seconds = max(0, int(seconds or 0))
        window_id = str(window_id or "").strip()
        if not window_id:
            return 0
        with self._connect() as conn:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO window_usage (
                    usage_date, resource_type, resource_id, window_id, usage_seconds, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(usage_date, resource_type, resource_id, window_id) DO UPDATE SET
                    usage_seconds = usage_seconds + excluded.usage_seconds,
                    updated_at = excluded.updated_at
                """,
                (usage_date, resource_type, resource_id, window_id, seconds, updated_at),
            )
            row = conn.execute(
                """
                SELECT usage_seconds FROM window_usage
                WHERE usage_date = ? AND resource_type = ? AND resource_id = ? AND window_id = ?
                """,
                (usage_date, resource_type, resource_id, window_id),
            ).fetchone()
            conn.commit()
        return int(row["usage_seconds"] if row else seconds)

    def get_windows(self, usage_date: str, resource_type: str, resource_id: str) -> Dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT window_id, usage_seconds FROM window_usage
                WHERE usage_date = ? AND resource_type = ? AND resource_id = ?
                ORDER BY window_id
                """,
                (usage_date, resource_type, resource_id),
            ).fetchall()
        return {str(row["window_id"]): int(row["usage_seconds"] or 0) for row in rows}

    def get_all_windows_for_date(self, usage_date: str) -> Dict[Tuple[str, str], Dict[str, int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT resource_type, resource_id, window_id, usage_seconds FROM window_usage
                WHERE usage_date = ?
                ORDER BY resource_type, resource_id, window_id
                """,
                (usage_date,),
            ).fetchall()
        out: Dict[Tuple[str, str], Dict[str, int]] = {}
        for row in rows:
            key = (str(row["resource_type"]), str(row["resource_id"]))
            out.setdefault(key, {})[str(row["window_id"])] = int(row["usage_seconds"] or 0)
        return out

    def get_sessions_on_date(self, usage_date: str) -> List[SessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM usage_sessions
                WHERE started_at LIKE ?
                ORDER BY started_at, id
                """,
                (f"{usage_date}%",),
            ).fetchall()
        return [_row_session(row) for row in rows]

    def list_activity_dates(self) -> List[str]:
        dates = set()
        with self._connect() as conn:
            for sql in (
                "SELECT DISTINCT usage_date FROM daily_usage",
                "SELECT DISTINCT usage_date FROM window_usage",
                "SELECT DISTINCT usage_date FROM browse_visits",
                "SELECT DISTINCT usage_date FROM watch_history",
                "SELECT DISTINCT substr(started_at, 1, 10) FROM usage_sessions",
            ):
                for row in conn.execute(sql).fetchall():
                    value = str(row[0] or "").strip()
                    if len(value) >= 10:
                        dates.add(value[:10])
        return sorted(dates)

    def start_session(
        self,
        resource_type: str,
        resource_id: str,
        started_at: str,
        pid: Optional[int] = None,
        identifier: str = "",
        created_at: str = "",
    ) -> int:
        created_at = created_at or started_at
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO usage_sessions (
                    resource_type, resource_id, started_at, duration_seconds, pid, identifier, created_at
                )
                VALUES (?, ?, ?, 0, ?, ?, ?)
                """,
                (resource_type, resource_id, started_at, pid, identifier or "", created_at),
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

    def get_open_session(self, resource_type: str, resource_id: str) -> Optional[SessionRecord]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM usage_sessions
                WHERE resource_type = ? AND resource_id = ? AND ended_at IS NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (resource_type, resource_id),
            ).fetchone()
        return _row_session(row) if row else None

    def get_open_sessions(self) -> List[SessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM usage_sessions WHERE ended_at IS NULL ORDER BY id"
            ).fetchall()
        return [_row_session(row) for row in rows]

    def record_warning(
        self,
        usage_date: str,
        resource_type: str,
        resource_id: str,
        warning_key: str,
        triggered_at: str = "",
    ) -> bool:
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO warning_state (
                        usage_date, resource_type, resource_id, warning_key, triggered_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (usage_date, resource_type, resource_id, warning_key, triggered_at or None),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def has_warning(self, usage_date: str, resource_type: str, resource_id: str, warning_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM warning_state
                WHERE usage_date = ? AND resource_type = ? AND resource_id = ? AND warning_key = ?
                """,
                (usage_date, resource_type, resource_id, warning_key),
            ).fetchone()
        return row is not None

    def get_browse_visits(self, usage_date: str) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM browse_visits WHERE usage_date = ? ORDER BY id",
                (usage_date,),
            ).fetchall()
        return [_row_visit(row) for row in rows]

    def add_browse_visit(
        self,
        usage_date: str,
        resource_id: str,
        host: str,
        url: str,
        title: str,
        seconds: int,
        seen_at: str,
        browser_resource_id: str = "",
        browser_name: str = "",
        resource_type: str = RESOURCE_TYPE_WEBSITE,
        max_rows: int = MAX_BROWSE_VISITS,
    ) -> str:
        host = str(host or "").strip()
        url = str(url or "").strip()
        resource_id = str(resource_id or "").strip() or website_id(host)
        if not host or not url or not resource_id:
            return "skipped"
        title = str(title or "")
        browser_resource_id = str(browser_resource_id or "").strip()
        browser_name = str(browser_name or "").strip()
        resource_type = str(resource_type or RESOURCE_TYPE_WEBSITE).strip() or RESOURCE_TYPE_WEBSITE
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
                        resource_id = CASE WHEN ? != '' THEN ? ELSE resource_id END,
                        browser_resource_id = CASE WHEN ? != '' THEN ? ELSE browser_resource_id END,
                        browser_name = CASE WHEN ? != '' THEN ? ELSE browser_name END
                    WHERE id = ?
                    """,
                    (
                        seen_at,
                        seconds,
                        title,
                        title,
                        host,
                        host,
                        resource_id,
                        resource_id,
                        browser_resource_id,
                        browser_resource_id,
                        browser_name,
                        browser_name,
                        last["id"],
                    ),
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
                    usage_date, resource_type, resource_id, host, url, title,
                    browser_resource_id, browser_name, first_seen, last_seen, usage_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage_date,
                    resource_type,
                    resource_id,
                    host,
                    url,
                    title,
                    browser_resource_id or None,
                    browser_name,
                    seen_at,
                    seen_at,
                    seconds,
                ),
            )
            conn.commit()
        return "inserted"

    def get_watches(
        self,
        usage_date: str,
        resource_id: str,
        resource_type: str = RESOURCE_TYPE_VIDEO_CATEGORY,
    ) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM watch_history
                WHERE usage_date = ? AND resource_type = ? AND resource_id = ?
                ORDER BY id
                """,
                (usage_date, resource_type, resource_id),
            ).fetchall()
        return [_row_watch(row) for row in rows]

    def add_watch(
        self,
        usage_date: str,
        resource_id: str,
        video: dict,
        seconds: int,
        seen_at: str,
        resource_type: str = RESOURCE_TYPE_VIDEO_CATEGORY,
        platform: str = "youtube",
        max_rows: int = MAX_WATCHES,
    ) -> str:
        if not isinstance(video, dict):
            return "skipped"
        video_id = str(video.get("id") or video.get("video_id") or "").strip()
        if not video_id:
            return "skipped"
        title = str(video.get("title") or "")
        channel = str(video.get("channel") or "")
        url = str(video.get("url") or "")
        seconds = max(0, int(seconds or 0))
        resource_type = str(resource_type or RESOURCE_TYPE_VIDEO_CATEGORY).strip() or RESOURCE_TYPE_VIDEO_CATEGORY
        platform = str(platform or "youtube").strip() or "youtube"
        with self._connect() as conn:
            last = conn.execute(
                """
                SELECT * FROM watch_history
                WHERE usage_date = ? AND resource_type = ? AND resource_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (usage_date, resource_type, resource_id),
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
                """
                SELECT COUNT(*) FROM watch_history
                WHERE usage_date = ? AND resource_type = ? AND resource_id = ?
                """,
                (usage_date, resource_type, resource_id),
            ).fetchone()[0]
            if int(count) >= int(max_rows):
                return "full"
            conn.execute(
                """
                INSERT INTO watch_history (
                    usage_date, resource_type, resource_id, platform, video_id, title, channel, url,
                    first_seen, last_seen, usage_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage_date,
                    resource_type,
                    resource_id,
                    platform,
                    video_id,
                    title,
                    channel,
                    url,
                    seen_at,
                    seen_at,
                    seconds,
                ),
            )
            conn.commit()
        return "inserted"
