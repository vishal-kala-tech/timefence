import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .policy import limit_seconds, matching_window
from .usage import load_state

GRANTS_NAME = "grants.json"
BONUS_WINDOW_ID = "bonus"


def parse_when(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def end_of_day(now):
    return datetime.combine(now.date() + timedelta(days=1), datetime.min.time())


def grant_expiry(now, minutes):
    minutes = max(1, int(minutes))
    return min(now + timedelta(minutes=minutes), end_of_day(now))


def format_when(value):
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    return str(value)


def active_grant(grant, now=None):
    now = now or datetime.now()
    if not isinstance(grant, dict):
        return None
    expires = parse_when(grant.get("expires_at"))
    if expires is None or now >= expires:
        return None
    return grant


def _extra_daily(grant):
    try:
        return max(0, int(grant.get("extra_daily_seconds") or 0))
    except (TypeError, ValueError):
        return 0


def _extra_window(grant, window_id):
    extras = grant.get("extra_windows") if isinstance(grant.get("extra_windows"), dict) else {}
    try:
        return max(0, int(extras.get(str(window_id)) or 0))
    except (TypeError, ValueError):
        return 0


def effective_daily_limit(policy, grant=None, now=None):
    base = limit_seconds((policy or {}).get("daily_limit_minutes"))
    grant = active_grant(grant, now=now)
    if not base:
        return 0
    return base + (_extra_daily(grant) if grant else 0)


def effective_window_limit(window, grant=None, now=None):
    if not window:
        return 0
    base = limit_seconds(window.get("limit_minutes"))
    grant = active_grant(grant, now=now)
    if not base:
        return 0
    return base + (_extra_window(grant, window.get("id")) if grant else 0)


def bonus_window(grant, now=None):
    now = now or datetime.now()
    grant = active_grant(grant, now=now)
    if not grant:
        return None
    until = parse_when(grant.get("allow_until") or grant.get("expires_at"))
    if until is None or now >= until:
        return None
    return {
        "id": BONUS_WINDOW_ID,
        "start": "00:00",
        "end": "24:00",
        "limit_minutes": None,
    }


def empty_grants(now=None):
    now = now or datetime.now()
    return {"date": now.date().isoformat(), "grants": {}}


def grants_path(state_dir):
    return Path(state_dir) / GRANTS_NAME


def load_grants(state_dir, now=None):
    now = now or datetime.now()
    path = grants_path(state_dir)
    if not path.exists():
        return empty_grants(now)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError, TypeError) as exc:
        logging.warning("Corrupt grants file (%s); ignoring", exc)
        return empty_grants(now)
    if not isinstance(data, dict) or data.get("date") != now.date().isoformat():
        return empty_grants(now)
    grants = data.get("grants") if isinstance(data.get("grants"), dict) else {}
    return {"date": data["date"], "grants": grants}


def load_grant(state_dir, resource, now=None):
    now = now or datetime.now()
    grant = load_grants(state_dir, now=now)["grants"].get(resource)
    return active_grant(grant, now=now)


def _save_grants(state_dir, payload):
    path = grants_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)
    return path


def save_grant(state_dir, resource, grant, now=None):
    now = now or datetime.now()
    payload = load_grants(state_dir, now=now)
    payload["date"] = now.date().isoformat()
    grants = payload.setdefault("grants", {})
    if grant is None:
        grants.pop(resource, None)
    else:
        grants[resource] = grant
    _save_grants(state_dir, payload)
    return grant


def clear_grant(state_dir, resource, now=None):
    return save_grant(state_dir, resource, None, now=now)


def _merge(existing, new, now):
    current = active_grant(existing, now=now)
    if not current:
        return new
    extra_windows = dict(current.get("extra_windows") or {})
    for window_id, seconds in (new.get("extra_windows") or {}).items():
        extra_windows[str(window_id)] = _extra_window(current, window_id) + int(seconds or 0)
    old_until = parse_when(current.get("expires_at"))
    new_until = parse_when(new.get("expires_at"))
    expires = new_until
    if old_until and (expires is None or old_until > expires):
        expires = old_until
    allow = parse_when(new.get("allow_until"))
    old_allow = parse_when(current.get("allow_until"))
    if old_allow and (allow is None or old_allow > allow):
        allow = old_allow
    if expires and (allow is None or allow < expires):
        allow = expires
    return {
        "minutes": int(new.get("minutes") or current.get("minutes") or 0),
        "granted_at": new.get("granted_at") or current.get("granted_at"),
        "expires_at": format_when(expires) if expires else new.get("expires_at"),
        "allow_until": format_when(allow) if allow else None,
        "extra_daily_seconds": _extra_daily(current) + _extra_daily(new),
        "extra_windows": extra_windows,
        "reason": new.get("reason") or current.get("reason"),
    }


def plan_grant(policy, state, minutes, now=None):
    from .policy import evaluate

    now = now or datetime.now()
    minutes = int(minutes)
    if minutes < 1:
        raise ValueError("Grant minutes must be at least 1")
    seconds = minutes * 60
    expires = grant_expiry(now, minutes)
    standing = evaluate(policy, state, now=now, grant=None)
    extra_daily = 0
    extra_windows = {}
    if limit_seconds(policy.get("daily_limit_minutes")):
        extra_daily = seconds
    window = standing.window or matching_window(policy, now=now)
    if window and limit_seconds(window.get("limit_minutes")):
        extra_windows[str(window.get("id"))] = seconds
    return {
        "minutes": minutes,
        "granted_at": format_when(now),
        "expires_at": format_when(expires),
        "allow_until": format_when(expires),
        "extra_daily_seconds": extra_daily,
        "extra_windows": extra_windows,
        "reason": standing.reason if not standing.allowed else "ok",
    }


def apply_grant(state_dir, resource, policy, minutes, now=None):
    now = now or datetime.now()
    state = load_state(state_dir, resource, now=now)
    planned = plan_grant(policy, state, minutes, now=now)
    merged = _merge(load_grants(state_dir, now=now)["grants"].get(resource), planned, now)
    save_grant(state_dir, resource, merged, now=now)
    logging.info(
        "Granted %s +%s min until %s reason=%s extra_daily=%ss extra_windows=%s",
        resource,
        minutes,
        merged.get("expires_at"),
        merged.get("reason"),
        merged.get("extra_daily_seconds") or 0,
        merged.get("extra_windows") or {},
    )
    return merged


def find_resource(cfg, name):
    resources = (cfg or {}).get("resources") or {}
    key = str(name or "").strip().lower()
    if not key:
        return None, None
    if key in resources:
        return key, resources[key]
    for resource_id, resource in resources.items():
        if not isinstance(resource, dict):
            continue
        label = str(resource.get("display_name") or resource_id).strip().lower()
        if label == key:
            return resource_id, resource
    return None, None


def grant_summary(grant, now=None):
    now = now or datetime.now()
    grant = active_grant(grant, now=now)
    if not grant:
        return None
    until = parse_when(grant.get("expires_at"))
    clock = until.strftime("%I:%M %p").lstrip("0") if until else ""
    if clock:
        return f"Bonus until {clock}"
    return "Bonus time"


def list_grants(cfg, state_dir, now=None):
    now = now or datetime.now()
    lines = []
    stored = load_grants(state_dir, now=now)["grants"]
    for name, resource in (cfg.get("resources") or {}).items():
        if not isinstance(resource, dict):
            continue
        grant = active_grant(stored.get(name), now=now)
        if not grant:
            continue
        label = resource.get("display_name") or name
        lines.append(f"{label}: {grant_summary(grant, now=now)}")
    return lines


def grant_from_config(cfg, state_dir, name, minutes, now=None):
    from .policy import resolve_policy

    now = now or datetime.now()
    resource_id, resource = find_resource(cfg, name)
    if resource_id is None:
        raise ValueError(f"Unknown resource {name!r}")
    if not resource.get("enabled", True):
        raise ValueError(f"{resource_id} is disabled")
    policy = resolve_policy(resource, now=now)
    return resource_id, apply_grant(state_dir, resource_id, policy, minutes, now=now)
