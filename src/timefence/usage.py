import json
import logging
from datetime import date, datetime
from pathlib import Path

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


def _path(state_dir, resource, now=None):
    return Path(state_dir) / resource / f"{_day(now).isoformat()}.json"


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
    for json_path in sorted(state_dir.glob(f"*/{day}.json")):
        resource = json_path.parent.name
        state = load_state(state_dir, resource, now=day)
        rows.append(_usage_row(day, resource, "daily", seconds=state.get("total_usage_seconds", 0)))
        for window_id, payload in sorted((state.get("windows") or {}).items()):
            rows.append(
                _usage_row(
                    day,
                    resource,
                    "window",
                    window=window_id,
                    seconds=(payload or {}).get("usage_seconds", 0),
                )
            )
        for video in state.get("videos") or []:
            rows.append(
                _usage_row(
                    day,
                    resource,
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


def load_state(state_dir, resource, now=None):
    path = _path(state_dir, resource, now=now)
    if not path.exists():
        return empty_state(now)
    try:
        return _normalize(json.loads(path.read_text()), now=now)
    except (OSError, ValueError, TypeError) as exc:
        logging.warning("Corrupt usage state for %s (%s); resetting", resource, exc)
        return empty_state(now)


def _save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)
    try:
        write_usage_table(path.parent.parent, now=state.get("date"))
    except Exception:
        logging.exception("Usage table export failed")


def get_usage(state_dir, resource, window_id=None, now=None):
    state = load_state(state_dir, resource, now=now)
    if window_id:
        return int((state["windows"].get(window_id) or {}).get("usage_seconds", 0))
    return int(state["total_usage_seconds"])


def add_usage(state_dir, resource, seconds, window_id=None, now=None, video=None):
    path = _path(state_dir, resource, now=now)
    state = load_state(state_dir, resource, now=now)
    state["date"] = _day(now).isoformat()
    state["total_usage_seconds"] = int(state["total_usage_seconds"]) + int(seconds)
    if window_id:
        window = state["windows"].setdefault(window_id, {"usage_seconds": 0, "warnings_sent": []})
        window["usage_seconds"] = int(window.get("usage_seconds", 0)) + int(seconds)
        window.setdefault("warnings_sent", [])
    if video:
        _append_watch(state, video, seconds, now)
    _save(path, state)
    return state


def note_video(state_dir, resource, video, now=None):
    path = _path(state_dir, resource, now=now)
    state = load_state(state_dir, resource, now=now)
    state["date"] = _day(now).isoformat()
    _append_watch(state, video, 0, now)
    _save(path, state)
    return state


def mark_warning_sent(state_dir, resource, warning, now=None):
    path = _path(state_dir, resource, now=now)
    state = load_state(state_dir, resource, now=now)
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
