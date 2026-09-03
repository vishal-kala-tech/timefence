"""Persist standing rules in SQLite. JSON is the seed; the DB is canonical.

Rule configuration tables live in `state/screen_time.sqlite` next to usage
tables, but they are replaced independently. Observed activity never creates
`rule_resources` rows.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .identity import default_display_name

_DEFAULT_POLL_INTERVAL_SECONDS = 15
_DEFAULT_IDLE_THRESHOLD_SECONDS = 120
_DEFAULT_MAX_COUNTABLE_INTERVAL_SECONDS = 30

# Sunday=0 ... Saturday=6. Matches SQLite/JS, not Python date.weekday().
WEEKDAY_NAME_TO_DOW = {
    "sunday": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}
DOW_TO_WEEKDAY_NAME = {value: key for key, value in WEEKDAY_NAME_TO_DOW.items()}
WEEKDAY_DOWS = (1, 2, 3, 4, 5)
WEEKEND_DOWS = (0, 6)

EFFECTIVE_POLICY_SQL = """
SELECT *
FROM rule_policies
WHERE resource_id = ?
  AND (
    (policy_type = 'date' AND policy_date = ?)
    OR (policy_type = 'day' AND day_of_week = ?)
    OR policy_type = 'default'
  )
ORDER BY CASE policy_type
    WHEN 'date' THEN 0
    WHEN 'day' THEN 1
    ELSE 2
END
LIMIT 1
"""


def day_of_week_for_date(value):
    """Map a date to Sunday=0 ... Saturday=6."""
    if isinstance(value, str):
        value = datetime.strptime(value[:10], "%Y-%m-%d").date()
    elif isinstance(value, datetime):
        value = value.date()
    return (value.weekday() + 1) % 7


def _connect(path):
    conn = sqlite3.connect(path)
    conn.isolation_level = None
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_schema(path):
    from .tracking.sqlite_usage_store import SqliteUsageStore

    SqliteUsageStore(path)


def _int(value, default=0):
    if value is None or value == "":
        return int(default)
    return int(float(value))


def _bool_int(value, default=0):
    if value is None:
        return int(default)
    return 1 if value else 0


def has_rules(path) -> bool:
    path = Path(path)
    if not path.exists():
        return False
    with _connect(path) as conn:
        try:
            row = conn.execute("SELECT 1 FROM rule_settings WHERE id = 1 LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            return False
    return row is not None


def save_rules(path, cfg):
    """Replace standing rules atomically. Caller must validate first."""
    path = Path(path)
    _ensure_schema(path)
    conn = _connect(path)
    try:
        conn.execute("BEGIN")
        _upsert_settings(conn, cfg or {})
        _upsert_screen_time(conn, cfg or {})
        conn.execute("DELETE FROM rule_resources")
        for resource in (cfg or {}).get("resources") or []:
            _insert_resource(conn, resource)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_rules(path) -> dict:
    path = Path(path)
    with _connect(path) as conn:
        settings = conn.execute("SELECT * FROM rule_settings WHERE id = 1").fetchone()
        if settings is None:
            raise ValueError("No rules are stored in the database")
        cfg = {
            "version": int(settings["version"]),
            "revision": int(settings["revision"]),
            "check_interval_seconds": int(settings["check_interval_seconds"]),
            "log_browsing": bool(settings["log_browsing"]),
            "resources": [],
        }
        screen_time = conn.execute(
            "SELECT * FROM rule_screen_time_settings WHERE id = 1"
        ).fetchone()
        if screen_time is not None:
            cfg["screen_time"] = {
                "enabled": bool(screen_time["enabled"]),
                "poll_interval_seconds": int(screen_time["poll_interval_seconds"]),
                "idle_threshold_seconds": int(screen_time["idle_threshold_seconds"]),
                "max_countable_interval_seconds": int(screen_time["max_countable_interval_seconds"]),
            }
        rows = conn.execute("SELECT * FROM rule_resources ORDER BY rowid").fetchall()
        for row in rows:
            cfg["resources"].append(_load_resource(conn, row))
    return cfg


def fetch_effective_policy(conn, resource_id, on_date):
    """Return the most specific policy row for a resource on YYYY-MM-DD."""
    on_date = str(on_date)[:10]
    return conn.execute(
        EFFECTIVE_POLICY_SQL,
        (resource_id, on_date, day_of_week_for_date(on_date)),
    ).fetchone()


def _upsert_settings(conn, cfg):
    conn.execute(
        """
        INSERT INTO rule_settings (
            id, version, revision, check_interval_seconds, log_browsing
        ) VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            version = excluded.version,
            revision = excluded.revision,
            check_interval_seconds = excluded.check_interval_seconds,
            log_browsing = excluded.log_browsing
        """,
        (
            _int(cfg.get("version"), 1),
            _int(cfg.get("revision"), 0),
            _int(cfg.get("check_interval_seconds"), 15),
            _bool_int(cfg.get("log_browsing"), 0),
        ),
    )


def _upsert_screen_time(conn, cfg):
    raw = cfg.get("screen_time") if isinstance(cfg.get("screen_time"), dict) else {}
    poll = raw.get("poll_interval_seconds")
    if poll is None:
        poll = cfg.get("check_interval_seconds", 15)
    conn.execute(
        """
        INSERT INTO rule_screen_time_settings (
            id, enabled, poll_interval_seconds, idle_threshold_seconds,
            max_countable_interval_seconds
        ) VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            enabled = excluded.enabled,
            poll_interval_seconds = excluded.poll_interval_seconds,
            idle_threshold_seconds = excluded.idle_threshold_seconds,
            max_countable_interval_seconds = excluded.max_countable_interval_seconds
        """,
        (
            _bool_int(raw.get("enabled"), 1),
            _int(poll, _DEFAULT_POLL_INTERVAL_SECONDS),
            _int(raw.get("idle_threshold_seconds"), _DEFAULT_IDLE_THRESHOLD_SECONDS),
            _int(raw.get("max_countable_interval_seconds"), _DEFAULT_MAX_COUNTABLE_INTERVAL_SECONDS),
        ),
    )


def _insert_resource(conn, resource):
    resource = resource or {}
    resource_id = str(resource.get("resource_id") or "").strip()
    resource_type = str(resource.get("resource_type") or "").strip()
    display_name = str(resource.get("display_name") or "").strip()
    if not display_name:
        display_name = default_display_name(resource_type, resource_id)
    module = str(resource.get("module") or "").strip() or None
    process_pattern = str(resource.get("process_pattern") or "").strip() or None
    conn.execute(
        """
        INSERT INTO rule_resources (
            resource_id, resource_type, display_name, module, process_pattern, enabled
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            resource_id,
            resource_type,
            display_name,
            module,
            process_pattern,
            1 if resource.get("enabled", True) else 0,
        ),
    )
    for match_id in resource.get("match_ids") or []:
        text = str(match_id or "").strip()
        if not text:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO rule_resource_match_ids (resource_id, match_id)
            VALUES (?, ?)
            """,
            (resource_id, text),
        )
    browsers = resource.get("browsers")
    if isinstance(browsers, str):
        browsers = [browsers]
    for browser in browsers or []:
        text = str(browser or "").strip()
        if not text:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO rule_resource_browsers (resource_id, browser)
            VALUES (?, ?)
            """,
            (resource_id, text),
        )
    for filter_type, key in (("include", "url_contains"), ("exclude", "url_excludes")):
        for pattern in resource.get(key) or []:
            text = str(pattern or "").strip()
            if not text:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO rule_url_filters (resource_id, filter_type, pattern)
                VALUES (?, ?, ?)
                """,
                (resource_id, filter_type, text),
            )
    for policy_type, day_of_week, policy_date, day_policy in _policy_entries(resource.get("policy")):
        _insert_policy(conn, resource_id, policy_type, day_of_week, policy_date, day_policy)


def _policy_entries(policy):
    if not isinstance(policy, dict):
        return []
    entries = []
    seen_days = set()
    days = policy.get("days") if isinstance(policy.get("days"), dict) else {}
    for name, day_policy in days.items():
        dow = WEEKDAY_NAME_TO_DOW.get(str(name or "").strip().lower())
        if dow is None:
            continue
        entries.append(("day", dow, None, day_policy))
        seen_days.add(dow)
    overrides = policy.get("date_overrides") if isinstance(policy.get("date_overrides"), dict) else {}
    for date_key, day_policy in overrides.items():
        text = str(date_key or "").strip()
        if not text:
            continue
        entries.append(("date", None, text, day_policy))
    if "default" in policy:
        entries.append(("default", None, None, policy["default"]))
    # Legacy JSON keys. Only expand when there is no default; resolve_policy
    # prefers default over weekday/weekend, and day rows would otherwise win.
    if "weekday" in policy and "default" not in policy:
        for dow in WEEKDAY_DOWS:
            if dow not in seen_days:
                entries.append(("day", dow, None, policy["weekday"]))
                seen_days.add(dow)
    if "weekend" in policy and "default" not in policy:
        for dow in WEEKEND_DOWS:
            if dow not in seen_days:
                entries.append(("day", dow, None, policy["weekend"]))
                seen_days.add(dow)
    return entries


def _insert_policy(conn, resource_id, policy_type, day_of_week, policy_date, day_policy):
    if not isinstance(day_policy, dict):
        return
    cursor = conn.execute(
        """
        INSERT INTO rule_policies (
            resource_id, policy_type, day_of_week, policy_date, daily_limit_minutes, has_windows
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            resource_id,
            policy_type,
            day_of_week,
            policy_date,
            _int(day_policy.get("daily_limit_minutes"), 0),
            1 if "allowed_windows" in day_policy else 0,
        ),
    )
    policy_id = int(cursor.lastrowid)
    for minutes in day_policy.get("warning_minutes") or []:
        conn.execute(
            """
            INSERT OR IGNORE INTO rule_policy_warnings (policy_id, warning_minutes)
            VALUES (?, ?)
            """,
            (policy_id, _int(minutes)),
        )
    if "allowed_windows" not in day_policy:
        return
    for window in day_policy.get("allowed_windows") or []:
        if not isinstance(window, dict):
            continue
        window_key = str(window.get("id") or "").strip()
        if not window_key:
            continue
        has_limit = "limit_minutes" in window and window.get("limit_minutes") is not None
        cursor = conn.execute(
            """
            INSERT INTO rule_windows (
                policy_id, window_key, start_time, end_time, limit_minutes
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                policy_id,
                window_key,
                str(window.get("start") or "00:00"),
                str(window.get("end") or "24:00"),
                _int(window.get("limit_minutes")) if has_limit else None,
            ),
        )
        window_id = int(cursor.lastrowid)
        for minutes in window.get("warning_minutes") or []:
            conn.execute(
                """
                INSERT OR IGNORE INTO rule_window_warnings (window_id, warning_minutes)
                VALUES (?, ?)
                """,
                (window_id, _int(minutes)),
            )


def _load_resource(conn, row) -> dict:
    resource_id = row["resource_id"]
    resource = {
        "resource_type": row["resource_type"],
        "resource_id": resource_id,
        "display_name": row["display_name"],
        "enabled": bool(row["enabled"]),
        "policy": {},
    }
    if row["module"]:
        resource["module"] = row["module"]
    if row["process_pattern"]:
        resource["process_pattern"] = row["process_pattern"]
    match_ids = [
        item["match_id"]
        for item in conn.execute(
            """
            SELECT match_id FROM rule_resource_match_ids
            WHERE resource_id = ?
            ORDER BY rowid
            """,
            (resource_id,),
        )
    ]
    if match_ids:
        resource["match_ids"] = match_ids
    browsers = [
        item["browser"]
        for item in conn.execute(
            """
            SELECT browser FROM rule_resource_browsers
            WHERE resource_id = ?
            ORDER BY rowid
            """,
            (resource_id,),
        )
    ]
    if browsers:
        resource["browsers"] = browsers
    contains = []
    excludes = []
    for item in conn.execute(
        """
        SELECT filter_type, pattern FROM rule_url_filters
        WHERE resource_id = ?
        ORDER BY id
        """,
        (resource_id,),
    ):
        if item["filter_type"] == "exclude":
            excludes.append(item["pattern"])
        else:
            contains.append(item["pattern"])
    if contains:
        resource["url_contains"] = contains
    if excludes:
        resource["url_excludes"] = excludes
    resource["policy"] = _load_policy(conn, resource_id)
    return resource


def _load_policy(conn, resource_id) -> dict:
    policy = {}
    days = {}
    overrides = {}
    rows = conn.execute(
        """
        SELECT * FROM rule_policies
        WHERE resource_id = ?
        ORDER BY policy_id
        """,
        (resource_id,),
    ).fetchall()
    for row in rows:
        day = _load_day_policy(conn, row)
        if row["policy_type"] == "default":
            policy["default"] = day
        elif row["policy_type"] == "day":
            name = DOW_TO_WEEKDAY_NAME.get(int(row["day_of_week"]))
            if name:
                days[name] = day
        elif row["policy_type"] == "date":
            overrides[str(row["policy_date"])] = day
    if days:
        policy["days"] = days
    if overrides:
        policy["date_overrides"] = overrides
    return policy


def _load_day_policy(conn, row) -> dict:
    day = {"daily_limit_minutes": int(row["daily_limit_minutes"] or 0)}
    warnings = [
        int(item["warning_minutes"])
        for item in conn.execute(
            """
            SELECT warning_minutes FROM rule_policy_warnings
            WHERE policy_id = ?
            ORDER BY warning_minutes DESC
            """,
            (row["policy_id"],),
        )
    ]
    if warnings:
        day["warning_minutes"] = warnings
    windows = []
    for window in conn.execute(
        """
        SELECT * FROM rule_windows
        WHERE policy_id = ?
        ORDER BY window_id
        """,
        (row["policy_id"],),
    ):
        item = {
            "id": window["window_key"],
            "start": window["start_time"],
            "end": window["end_time"],
        }
        if window["limit_minutes"] is not None:
            item["limit_minutes"] = int(window["limit_minutes"])
        window_warnings = [
            int(warn["warning_minutes"])
            for warn in conn.execute(
                """
                SELECT warning_minutes FROM rule_window_warnings
                WHERE window_id = ?
                ORDER BY warning_minutes DESC
                """,
                (window["window_id"],),
            )
        ]
        if window_warnings:
            item["warning_minutes"] = window_warnings
        windows.append(item)
    if row["has_windows"]:
        day["allowed_windows"] = windows
    return day
