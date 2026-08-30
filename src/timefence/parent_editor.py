import re

from .config import validate_config

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(value):
    text = _SLUG_RE.sub("_", str(value or "").strip().lower()).strip("_")
    return text or "window"


def _as_int(value, default=0):
    if value in (None, ""):
        return default
    return int(float(value))


def _warning_list(value, limit=None):
    if value in (None, ""):
        return []
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value).replace(";", ",").split(",")
    out = []
    seen = set()
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        number = int(float(text))
        if number <= 0 or number in seen:
            continue
        if limit not in (None, 0) and number > limit:
            continue
        seen.add(number)
        out.append(number)
    return out


def day_to_editor(policy):
    if not isinstance(policy, dict):
        return None
    windows = []
    for window in policy.get("allowed_windows") or []:
        if not isinstance(window, dict):
            continue
        window_id = str(window.get("id") or "").strip()
        if not window_id:
            continue
        item = {
            "id": window_id,
            "name": window_id.replace("_", " "),
            "start": window.get("start") or "16:00",
            "end": window.get("end") or "18:00",
            "limit_minutes": window.get("limit_minutes") if window.get("limit_minutes") is not None else 0,
            "warning_minutes": list(window.get("warning_minutes") or []),
        }
        windows.append(item)
    return {
        "daily_limit_minutes": policy.get("daily_limit_minutes") if policy.get("daily_limit_minutes") is not None else 0,
        "warning_minutes": list(policy.get("warning_minutes") or []),
        "windows": windows,
    }


def editor_to_day(payload):
    if not isinstance(payload, dict):
        raise ValueError("Day policy is missing")
    windows = []
    seen = set()
    for index, window in enumerate(payload.get("windows") or []):
        if not isinstance(window, dict):
            continue
        window_id = slug(window.get("id") or window.get("name") or f"window_{index + 1}")
        if window_id in seen:
            window_id = f"{window_id}_{index + 1}"
        seen.add(window_id)
        start = str(window.get("start") or "").strip() or "00:00"
        end = str(window.get("end") or "").strip() or "24:00"
        item = {"id": window_id, "start": start, "end": end}
        limit = _as_int(window.get("limit_minutes"), 0)
        if limit:
            item["limit_minutes"] = limit
        warnings = _warning_list(window.get("warning_minutes"), limit=limit)
        if warnings:
            item["warning_minutes"] = warnings
        windows.append(item)
    if not windows:
        windows = [{"id": "all_day", "start": "00:00", "end": "24:00"}]
    daily = max(0, _as_int(payload.get("daily_limit_minutes"), 0))
    day = {
        "daily_limit_minutes": daily,
        "allowed_windows": windows,
    }
    warnings = _warning_list(payload.get("warning_minutes"), limit=daily)
    if warnings:
        day["warning_minutes"] = warnings
    return day


def editor_from_config(cfg):
    resources = []
    for name, resource in (cfg.get("resources") or {}).items():
        if not isinstance(resource, dict):
            continue
        policy = resource.get("policy") or {}
        default = policy.get("default")
        if default is None:
            default = policy.get("weekday")
        days = policy.get("days") if isinstance(policy.get("days"), dict) else {}
        resources.append(
            {
                "id": name,
                "display_name": resource.get("display_name") or name,
                "enabled": bool(resource.get("enabled", True)),
                "default": day_to_editor(default) or day_to_editor({"daily_limit_minutes": 0, "allowed_windows": []}),
                "saturday": day_to_editor(days.get("saturday")),
                "sunday": day_to_editor(days.get("sunday")),
            }
        )
    return {
        "log_browsing": bool(cfg.get("log_browsing", True)),
        "resources": resources,
    }


def apply_editor(existing, editor):
    if not isinstance(editor, dict):
        raise ValueError("Editor payload must be an object")
    cfg = dict(existing or {})
    cfg["version"] = 1
    try:
        cfg["revision"] = int(cfg.get("revision") or 0) + 1
    except (TypeError, ValueError):
        cfg["revision"] = 1
    if "log_browsing" in editor:
        cfg["log_browsing"] = bool(editor.get("log_browsing"))
    resources = dict(cfg.get("resources") or {})
    for item in editor.get("resources") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("id") or "").strip()
        if name not in resources or not isinstance(resources[name], dict):
            continue
        resource = dict(resources[name])
        resource["enabled"] = bool(item.get("enabled", True))
        display = str(item.get("display_name") or "").strip()
        if display:
            resource["display_name"] = display
        policy = dict(resource.get("policy") or {})
        policy["default"] = editor_to_day(item.get("default") or {})
        days = dict(policy.get("days") or {})
        for day_name in ("saturday", "sunday"):
            payload = item.get(day_name)
            if payload:
                days[day_name] = editor_to_day(payload)
            else:
                days.pop(day_name, None)
        extra = {key: value for key, value in days.items() if key not in ("saturday", "sunday")}
        days = {**extra, **{key: days[key] for key in ("saturday", "sunday") if key in days}}
        if days:
            policy["days"] = days
        else:
            policy.pop("days", None)
        resource["policy"] = policy
        resources[name] = resource
    cfg["resources"] = resources
    return validate_config(cfg)
