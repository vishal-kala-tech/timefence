"""Same-day bonus time. Never changes standing `rules.json`.

A grant expires at `min(now + minutes, end of local day)`. Loading a file
dated yesterday returns empty: leftover bonus must not survive midnight.

Two ways to relax a block:
- extra_daily_seconds / extra_windows: raise the cap on an existing window
- allow_until + bonus_window: a synthetic all-day window so the child can
  use the resource *outside* standing hours

`apply_grant` stacks on an already-active grant (adds seconds, keeps the
later expiry) so two parent taps do not wipe the first.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .identity import listed_resources, resource_id_of, resource_key, resource_type_of
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
    """Cap at local midnight so a 60-minute grant at 11:30pm does not leak into tomorrow."""
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
    """Standing daily cap plus extra seconds from an active grant. 0 means no cap."""
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
    """Synthetic window used only when the child is outside standing hours."""
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
        # Yesterday's leftover bonus must not apply today.
        return empty_grants(now)
    grants = data.get("grants") if isinstance(data.get("grants"), dict) else {}
    return {"date": data["date"], "grants": grants}


def _grant_get(grants, resource_type, resource_id):
    bucket = grants.get(resource_type) if isinstance(grants, dict) else None
    if not isinstance(bucket, dict):
        return None
    return bucket.get(resource_id)


def _grant_set(grants, resource_type, resource_id, grant):
    bucket = grants.setdefault(resource_type, {})
    if grant is None:
        bucket.pop(resource_id, None)
        if not bucket:
            grants.pop(resource_type, None)
    else:
        bucket[resource_id] = grant


def load_grant(state_dir, resource_type, resource_id, now=None):
    now = now or datetime.now()
    grant = _grant_get(load_grants(state_dir, now=now)["grants"], resource_type, resource_id)
    return active_grant(grant, now=now)


def _save_grants(state_dir, payload):
    path = grants_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)
    return path


def save_grant(state_dir, resource_type, resource_id, grant, now=None):
    now = now or datetime.now()
    payload = load_grants(state_dir, now=now)
    payload["date"] = now.date().isoformat()
    grants = payload.setdefault("grants", {})
    _grant_set(grants, resource_type, resource_id, grant)
    _save_grants(state_dir, payload)
    return grant


def clear_grant(state_dir, resource_type, resource_id, now=None):
    return save_grant(state_dir, resource_type, resource_id, None, now=now)


def _merge(existing, new, now):
    """Stack extras onto a still-active grant; take the later expiry."""
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
    """Decide where the minutes go: daily extra, current-window extra, and/or bonus hours."""
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
    # Only raise a cap that already exists. Unlimited stays unlimited.
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


def apply_grant(state_dir, resource_type, resource_id, policy, minutes, now=None):
    now = now or datetime.now()
    state = load_state(state_dir, resource_type, resource_id, now=now)
    planned = plan_grant(policy, state, minutes, now=now)
    existing = _grant_get(load_grants(state_dir, now=now)["grants"], resource_type, resource_id)
    merged = _merge(existing, planned, now)
    save_grant(state_dir, resource_type, resource_id, merged, now=now)
    logging.info(
        "Granted %s/%s +%s min until %s reason=%s extra_daily=%ss extra_windows=%s",
        resource_type,
        resource_id,
        minutes,
        merged.get("expires_at"),
        merged.get("reason"),
        merged.get("extra_daily_seconds") or 0,
        merged.get("extra_windows") or {},
    )
    return merged


def find_resource(cfg, resource_type=None, resource_id=None, name=None):
    needle_type = str(resource_type or "").strip()
    needle_id = str(resource_id or name or "").strip().lower()
    if not needle_id:
        return None
    for resource in listed_resources(cfg):
        rtype = resource_type_of(resource)
        rid = resource_id_of(resource)
        if needle_type and rtype != needle_type:
            continue
        if rid.lower() == needle_id:
            return resource
        label = str(resource.get("display_name") or "").strip().lower()
        if label and label == needle_id and (not needle_type or rtype == needle_type):
            return resource
    return None


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


def grant_rows(cfg, state_dir, now=None):
    now = now or datetime.now()
    stored = load_grants(state_dir, now=now)["grants"]
    rows = []
    for resource in listed_resources(cfg):
        rtype, rid = resource_key(resource)
        grant = active_grant(_grant_get(stored, rtype, rid), now=now)
        if not grant:
            continue
        extra = _extra_daily(grant)
        rows.append(
            {
                "resource_type": rtype,
                "resource_id": rid,
                "display_name": resource.get("display_name") or rid,
                "minutes": grant.get("minutes") or 0,
                "extra_minutes": extra // 60,
                "expires_at": grant.get("expires_at"),
                "summary": grant_summary(grant, now=now),
            }
        )
    return rows


def list_grants(cfg, state_dir, now=None):
    return [f"{row['display_name']}: {row['summary']}" for row in grant_rows(cfg, state_dir, now=now)]


def grant_from_config(cfg, state_dir, resource_type, resource_id, minutes, now=None):
    from .policy import resolve_policy

    now = now or datetime.now()
    resource = find_resource(cfg, resource_type=resource_type, resource_id=resource_id)
    if resource is None:
        raise ValueError(f"Unknown resource {resource_type}/{resource_id}")
    if not resource.get("enabled", True):
        raise ValueError(f"{resource_type}/{resource_id} is disabled")
    policy = resolve_policy(resource, now=now)
    rtype, rid = resource_key(resource)
    return resource, apply_grant(state_dir, rtype, rid, policy, minutes, now=now)
