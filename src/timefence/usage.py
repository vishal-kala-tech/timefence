import json
import logging
from datetime import date, datetime
from pathlib import Path


def _day(now=None):
    if now is None:
        return date.today()
    if isinstance(now, datetime):
        return now.date()
    return now


def _path(state_dir, resource, now=None):
    return Path(state_dir) / resource / f"{_day(now).isoformat()}.json"


def empty_state(now=None):
    return {
        "date": _day(now).isoformat(),
        "total_usage_seconds": 0,
        "warnings_sent": [],
        "windows": {},
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


def get_usage(state_dir, resource, window_id=None, now=None):
    state = load_state(state_dir, resource, now=now)
    if window_id:
        return int((state["windows"].get(window_id) or {}).get("usage_seconds", 0))
    return int(state["total_usage_seconds"])


def add_usage(state_dir, resource, seconds, window_id=None, now=None):
    path = _path(state_dir, resource, now=now)
    state = load_state(state_dir, resource, now=now)
    state["date"] = _day(now).isoformat()
    state["total_usage_seconds"] = int(state["total_usage_seconds"]) + int(seconds)
    if window_id:
        window = state["windows"].setdefault(window_id, {"usage_seconds": 0, "warnings_sent": []})
        window["usage_seconds"] = int(window.get("usage_seconds", 0)) + int(seconds)
        window.setdefault("warnings_sent", [])
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
