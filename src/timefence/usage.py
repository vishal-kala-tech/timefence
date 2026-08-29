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
        "windows": {},
    }


def _normalize(data, now=None):
    if not isinstance(data, dict):
        return empty_state(now)
    total = data.get("total_usage_seconds", data.get("usage_seconds", 0))
    windows = data.get("windows") if isinstance(data.get("windows"), dict) else {}
    normalized = {
        "date": data.get("date") or _day(now).isoformat(),
        "total_usage_seconds": int(total or 0),
        "windows": {},
    }
    for window_id, payload in windows.items():
        if isinstance(payload, dict):
            normalized["windows"][str(window_id)] = {
                "usage_seconds": int(payload.get("usage_seconds", 0) or 0)
            }
        else:
            normalized["windows"][str(window_id)] = {"usage_seconds": int(payload or 0)}
    return normalized


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
        window = state["windows"].setdefault(window_id, {"usage_seconds": 0})
        window["usage_seconds"] = int(window.get("usage_seconds", 0)) + int(seconds)
    _save(path, state)
    return state
