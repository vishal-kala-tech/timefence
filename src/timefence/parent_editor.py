"""Translate between `rules.json` and the parent-editor JSON subset.

The UI only edits enabled, display name, weekday default, Saturday, and
Sunday. It cannot add resources, change `bundle_ids`, or rewrite
`date_overrides`. That keeps a PIN holder from inventing new apps or wiping
screen-time identifiers.

`editor_to_day` always emits at least one window (`all_day` 00:00–24:00). An
empty `allowed_windows` list would mean "never allowed"; the form must not
accidentally lock the child by clearing every window.

`apply_editor` bumps `revision` so the controller logs a reload.
"""

import re

from .config import validate_config
from .identity import listed_resources, resource_id_of, resource_type_of

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
        # Empty list would mean never allowed. Default to all-day instead of locking the child.
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
    """Subset the live file for the form. Weekend days are optional overlays on `default`."""
    resources = []
    for resource in listed_resources(cfg):
        policy = resource.get("policy") or {}
        default = policy.get("default")
        if default is None:
            default = policy.get("weekday")
        days = policy.get("days") if isinstance(policy.get("days"), dict) else {}
        rtype = resource_type_of(resource)
        rid = resource_id_of(resource)
        resources.append(
            {
                "resource_type": rtype,
                "resource_id": rid,
                "display_name": resource.get("display_name") or rid,
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
    """Patch enabled/names/schedules onto existing resources, then validate the whole file."""
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
    resources = list(listed_resources(cfg))
    by_key = {(resource_type_of(item), resource_id_of(item)): item for item in resources}
    for item in editor.get("resources") or []:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("resource_type") or "").strip(), str(item.get("resource_id") or "").strip())
        if key not in by_key:
            continue
        resource = dict(by_key[key])
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
        extra = {day_key: value for day_key, value in days.items() if day_key not in ("saturday", "sunday")}
        days = {**extra, **{day_key: days[day_key] for day_key in ("saturday", "sunday") if day_key in days}}
        if days:
            policy["days"] = days
        else:
            policy.pop("days", None)
        resource["policy"] = policy
        by_key[key] = resource
    cfg["resources"] = list(by_key.values())
    return validate_config(cfg)
