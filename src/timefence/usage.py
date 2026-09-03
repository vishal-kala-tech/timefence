"""JSON usage cache: `state/<resource_type>/<resource_id>/<date>.json`.

Daily totals, windows, and watch rows are stored in SQLite keyed by
(resource_type, resource_id). JSON keeps warning keys and a cache of the rest.
App rows are screen time. Website and video_category rows attribute the same
foreground interval and must not be summed into screen time.
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

from .identity import RESOURCE_TYPE_APP, RESOURCE_TYPE_VIDEO_CATEGORY

MAX_VIDEOS = 5000
USAGE_TABLE_FIELDS = (
    "date",
    "resource",
    "kind",
    "window",
    "seconds",
    "video_id",
    "title",
    "channel",
    "url",
    "first_seen",
    "last_seen",
)


def _day(now=None):
    if now is None:
        return date.today()
    if isinstance(now, datetime):
        return now.date()
    if isinstance(now, date):
        return now
    return datetime.strptime(str(now)[:10], "%Y-%m-%d").date()


def _path(state_dir, resource_type, resource_id, now=None):
    return Path(state_dir) / str(resource_type) / str(resource_id) / f"{_day(now).isoformat()}.json"


def usage_table_path(state_dir, now=None):
    return Path(state_dir) / f"{_day(now).isoformat()}.txt"


def _cell(value):
    text = "" if value is None else str(value)
    return text.replace("\r", " ").replace("\n", " ").replace("|", "/")


def _usage_row(day, resource, kind, window="", seconds=0, video=None):
    video = video or {}
    return "|".join(
        _cell(part)
        for part in (
            day,
            resource,
            kind,
            window,
            int(seconds or 0),
            video.get("id") or "",
            video.get("title") or "",
            video.get("channel") or "",
            video.get("url") or "",
            video.get("first_seen") or "",
            video.get("last_seen") or "",
        )
    )


def write_usage_table(state_dir, now=None):
    """Rewrite the day's pipe-separated usage file for Excel import."""
    day = _day(now).isoformat()
    state_dir = Path(state_dir)
    rows = ["|".join(USAGE_TABLE_FIELDS)]
    for json_path in sorted(state_dir.glob(f"*/*/{day}.json")):
        resource_id = json_path.parent.name
        resource_type = json_path.parent.parent.name
        if resource_type in ("browse", "config"):
            continue
        state = load_state(state_dir, resource_type, resource_id, now=day)
        rows.append(_usage_row(day, resource_id, "daily", seconds=state.get("total_usage_seconds", 0)))
        for window_id, payload in sorted((state.get("windows") or {}).items()):
            rows.append(
                _usage_row(
                    day,
                    resource_id,
                    "window",
                    window=window_id,
                    seconds=(payload or {}).get("usage_seconds", 0),
                )
            )
        for video in state.get("videos") or []:
            rows.append(
                _usage_row(
                    day,
                    resource_id,
                    "video",
                    seconds=video.get("usage_seconds", 0),
                    video=video,
                )
            )
    path = usage_table_path(state_dir, now=day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(rows) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def empty_state(now=None):
    return {
        "date": _day(now).isoformat(),
        "total_usage_seconds": 0,
        "warnings_sent": [],
        "windows": {},
        "videos": [],
    }


def _warning_list(values):
    if not isinstance(values, list):
        return []
    out = []
    seen = set()
    for item in values:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _window_state(payload):
    if isinstance(payload, dict):
        return {
            "usage_seconds": int(payload.get("usage_seconds", 0) or 0),
            "warnings_sent": _warning_list(payload.get("warnings_sent")),
        }
    return {"usage_seconds": int(payload or 0), "warnings_sent": []}


def _video_entry(payload):
    if not isinstance(payload, dict):
        return None
    video_id = str(payload.get("id") or "").strip()
    if not video_id:
        return None
    return {
        "id": video_id,
        "title": str(payload.get("title") or ""),
        "channel": str(payload.get("channel") or ""),
        "url": str(payload.get("url") or ""),
        "first_seen": str(payload.get("first_seen") or ""),
        "last_seen": str(payload.get("last_seen") or ""),
        "usage_seconds": int(payload.get("usage_seconds") or 0),
    }


def _videos(values):
    if not isinstance(values, list):
        return []
    out = []
    for item in values:
        entry = _video_entry(item)
        if entry:
            out.append(entry)
    return out


def _timestamp(now=None):
    if isinstance(now, datetime):
        return now.strftime("%H:%M:%S")
    if now is None:
        return datetime.now().strftime("%H:%M:%S")
    return str(now)


def _append_watch(state, video, seconds, now):
    """Append a watch-history row. Consecutive polls of the same id stay one session."""
    if not isinstance(video, dict):
        return False
    video_id = str(video.get("id") or "").strip()
    if not video_id:
        return False
    ts = _timestamp(now)
    title = str(video.get("title") or "")
    channel = str(video.get("channel") or "")
    url = str(video.get("url") or "")
    videos = state.setdefault("videos", [])
    if videos and videos[-1].get("id") == video_id:
        last = videos[-1]
        last["last_seen"] = ts
        last["usage_seconds"] = int(last.get("usage_seconds") or 0) + int(seconds)
        if title:
            last["title"] = title
        if channel:
            last["channel"] = channel
        if url:
            last["url"] = url
        return False
    if len(videos) >= MAX_VIDEOS:
        logging.warning("Watch history full (%s); not adding %s", MAX_VIDEOS, video_id)
        return False
    videos.append(
        {
            "id": video_id,
            "title": title,
            "channel": channel,
            "url": url,
            "first_seen": ts,
            "last_seen": ts,
            "usage_seconds": int(seconds),
        }
    )
    return True


def _normalize(data, now=None):
    if not isinstance(data, dict):
        return empty_state(now)
    total = data.get("total_usage_seconds", data.get("usage_seconds", 0))
    windows = data.get("windows") if isinstance(data.get("windows"), dict) else {}
    return {
        "date": data.get("date") or _day(now).isoformat(),
        "total_usage_seconds": int(total or 0),
        "warnings_sent": _warning_list(data.get("warnings_sent")),
        "windows": {str(window_id): _window_state(payload) for window_id, payload in windows.items()},
        "videos": _videos(data.get("videos")),
    }


def _sqlite_path(state_dir):
    return Path(state_dir) / "screen_time.sqlite"


def _sqlite_store(state_dir):
    from .tracking.sqlite_usage_store import SqliteUsageStore

    return SqliteUsageStore(_sqlite_path(state_dir))


def _updated_at(now=None):
    if isinstance(now, datetime):
        return now.replace(microsecond=0).isoformat()
    return datetime.now().replace(microsecond=0).isoformat()


def _overlay_window_usage(state, state_dir, resource_type, resource_id, now=None):
    """Prefer SQLite window seconds."""
    path = _sqlite_path(state_dir)
    if not path.exists():
        return state
    sqlite_windows = _sqlite_store(state_dir).get_windows(
        _day(now).isoformat(), resource_type, resource_id
    )
    if not sqlite_windows:
        return state
    windows = state.setdefault("windows", {})
    for window_id, seconds in sqlite_windows.items():
        window = windows.setdefault(window_id, {"usage_seconds": 0, "warnings_sent": []})
        window["usage_seconds"] = int(seconds)
    return state


def _overlay_watches(state, state_dir, resource_type, resource_id, now=None):
    """Prefer SQLite watch rows."""
    store = _sqlite_store(state_dir)
    usage_date = _day(now).isoformat()
    videos = store.get_watches(usage_date, resource_id, resource_type=resource_type)
    if videos:
        state["videos"] = videos
    return state


def _record_watch(state_dir, resource_type, resource_id, video, seconds, now):
    store = _sqlite_store(state_dir)
    usage_date = _day(now).isoformat()
    result = store.add_watch(
        usage_date,
        resource_id,
        video,
        int(seconds),
        _timestamp(now),
        resource_type=resource_type,
        max_rows=MAX_VIDEOS,
    )
    if result == "full":
        logging.warning("Watch history full (%s); not adding %s", MAX_VIDEOS, (video or {}).get("id"))
    return store.get_watches(usage_date, resource_id, resource_type=resource_type)


def _add_window_seconds(state_dir, resource_type, resource_id, window_id, seconds, now):
    store = _sqlite_store(state_dir)
    usage_date = _day(now).isoformat()
    stamp = _updated_at(now)
    return store.add_window_seconds(
        usage_date, resource_type, resource_id, window_id, int(seconds), stamp
    )


def load_state(state_dir, resource_type, resource_id, now=None):
    """Today's usage for one resource. Missing or corrupt file → empty totals, not an error."""
    path = _path(state_dir, resource_type, resource_id, now=now)
    if not path.exists():
        state = empty_state(now)
    else:
        try:
            state = _normalize(json.loads(path.read_text()), now=now)
        except (OSError, ValueError, TypeError) as exc:
            logging.warning("Corrupt usage state for %s/%s (%s); resetting", resource_type, resource_id, exc)
            state = empty_state(now)
    store = _sqlite_store(state_dir)
    usage_date = _day(now).isoformat()
    row = store.get_daily(usage_date, resource_type, resource_id)
    if row is not None:
        state["total_usage_seconds"] = int(row.total_active_seconds)
    return _overlay_watches(
        _overlay_window_usage(state, state_dir, resource_type, resource_id, now=now),
        state_dir,
        resource_type,
        resource_id,
        now=now,
    )


def _save(path, state):
    """Atomic JSON write, then rebuild the day's pipe-separated export for Excel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)
    try:
        write_usage_table(path.parent.parent.parent, now=state.get("date"))
    except Exception:
        logging.exception("Usage table export failed")


def get_usage(state_dir, resource_type, resource_id, window_id=None, now=None):
    state = load_state(state_dir, resource_type, resource_id, now=now)
    if window_id:
        return int((state["windows"].get(window_id) or {}).get("usage_seconds", 0))
    return int(state["total_usage_seconds"])


def add_usage(
    state_dir,
    resource_type,
    resource_id,
    seconds,
    window_id=None,
    now=None,
    video=None,
    credit_daily=True,
):
    """Increment today's totals. App screen-time ticks set credit_daily=False
    because UsageTracker already wrote the SQLite app row."""
    path = _path(state_dir, resource_type, resource_id, now=now)
    state = load_state(state_dir, resource_type, resource_id, now=now)
    state["date"] = _day(now).isoformat()
    stamp = _updated_at(now)
    if credit_daily:
        total = _sqlite_store(state_dir).add_active_seconds(
            state["date"], resource_type, resource_id, int(seconds), stamp
        )
        state["total_usage_seconds"] = total
    if window_id:
        total_window = _add_window_seconds(
            state_dir, resource_type, resource_id, window_id, int(seconds), now
        )
        window = state["windows"].setdefault(window_id, {"usage_seconds": 0, "warnings_sent": []})
        window["usage_seconds"] = total_window
        window.setdefault("warnings_sent", [])
    if video:
        state["videos"] = _record_watch(
            state_dir, resource_type, resource_id, video, seconds, now
        )
    _save(path, state)
    return state


def note_video(state_dir, resource_type, resource_id, video, now=None):
    path = _path(state_dir, resource_type, resource_id, now=now)
    state = load_state(state_dir, resource_type, resource_id, now=now)
    state["date"] = _day(now).isoformat()
    state["videos"] = _record_watch(state_dir, resource_type, resource_id, video, 0, now)
    _save(path, state)
    return state


def mark_warning_sent(state_dir, resource_type, resource_id, warning, now=None):
    """Persist a warning key so the same threshold does not re-alert this day."""
    path = _path(state_dir, resource_type, resource_id, now=now)
    state = load_state(state_dir, resource_type, resource_id, now=now)
    key = warning.persist_key if hasattr(warning, "persist_key") else str(warning)
    window_id = getattr(warning, "window_id", None)
    if window_id:
        window = state["windows"].setdefault(window_id, {"usage_seconds": 0, "warnings_sent": []})
        sent = window.setdefault("warnings_sent", [])
        if key not in sent:
            sent.append(key)
    else:
        sent = state.setdefault("warnings_sent", [])
        if key not in sent:
            sent.append(key)
    _save(path, state)
    return state
