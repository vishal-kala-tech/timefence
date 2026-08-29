from datetime import datetime
from pathlib import Path

from .config import load_config
from .policy import evaluate, limit_seconds, parse_hhmm, resource_label, resolve_policy
from .usage import load_state


def format_clock(seconds):
    seconds = max(0, int(seconds or 0))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if hours:
        parts.append("1 hour" if hours == 1 else f"{hours} hours")
    if minutes:
        parts.append("1 minute" if minutes == 1 else f"{minutes} minutes")
    if secs and not hours:
        parts.append("1 second" if secs == 1 else f"{secs} seconds")
    if not parts:
        return "0 seconds"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} and {parts[1]}"


def format_time_of_day(hhmm):
    total = parse_hhmm(hhmm)
    if total >= 24 * 60:
        return "midnight"
    hours, minutes = divmod(total, 60)
    suffix = "AM" if hours < 12 else "PM"
    hour12 = hours % 12 or 12
    return f"{hour12}:{minutes:02d} {suffix}"


def format_window_name(window_id):
    text = str(window_id or "window").replace("_", " ").strip()
    return text or "window"


def format_span(start, end):
    if start == "00:00" and end in ("24:00", "00:00"):
        return None
    return f"{format_time_of_day(start)} to {format_time_of_day(end)}"


def _allowed_phrase(limit):
    text = format_clock(limit)
    singular = text.startswith("1 ") and " and " not in text
    verb = "is" if singular else "are"
    return f"{text} {verb} allowed."


def remaining_seconds(limit, used):
    if not limit:
        return None
    return max(0, int(limit) - int(used or 0))


def _used_and_remaining(label, used, limit):
    if not limit:
        if not used:
            return f"{label} has not been used yet and has no time cap."
        return f"{label} has used {format_clock(used)} and has no time cap."
    allowed = format_clock(limit)
    remaining = remaining_seconds(limit, used)
    if not used:
        return f"{label} has not been used yet. {_allowed_phrase(limit)}"
    if remaining == 0:
        return f"{label} has used {format_clock(used)} of {allowed} allowed, so no time remains."
    return (
        f"{label} has used {format_clock(used)} of {allowed} allowed, "
        f"with {format_clock(remaining)} remaining."
    )


def _now_sentence(label, decision):
    if decision.allowed and decision.window:
        window = decision.window
        name = format_window_name(window.get("id"))
        span = format_span(window.get("start"), window.get("end"))
        if span:
            return f"{label} is allowed right now during the {name} window ({span})."
        return f"{label} is allowed right now during the {name} window."
    if decision.reason == "daily_limit":
        return f"{label} is not allowed right now because the daily limit has been reached."
    if decision.reason == "window_limit":
        name = format_window_name(decision.window_id)
        return (
            f"{label} is not allowed right now because the {name} window "
            "limit has been reached."
        )
    return f"{label} is not allowed right now because it is outside an allowed window."


def resource_budget(name, resource, state, now):
    policy = resolve_policy(resource, now=now)
    decision = evaluate(policy, state, now=now)
    daily_limit = limit_seconds(policy.get("daily_limit_minutes"))
    daily_used = int((state or {}).get("total_usage_seconds", 0))
    windows = []
    for window in policy.get("allowed_windows") or []:
        window_id = window.get("id")
        window_used = int(((state or {}).get("windows") or {}).get(window_id, {}).get("usage_seconds", 0))
        window_limit = limit_seconds(window.get("limit_minutes"))
        windows.append(
            {
                "id": window_id,
                "start": window.get("start"),
                "end": window.get("end"),
                "used": window_used,
                "limit": window_limit,
                "remaining": remaining_seconds(window_limit, window_used),
                "current": bool(decision.window and decision.window.get("id") == window_id),
            }
        )
    return {
        "name": name,
        "label": resource_label(name, resource),
        "enabled": bool(resource.get("enabled", True)),
        "now": _now_sentence(resource_label(name, resource), decision),
        "allowed": decision.allowed,
        "daily_used": daily_used,
        "daily_limit": daily_limit,
        "daily_remaining": remaining_seconds(daily_limit, daily_used),
        "windows": windows,
    }


def summarize(cfg, state_dir, now=None):
    now = now or datetime.now()
    rows = []
    for name, resource in (cfg.get("resources") or {}).items():
        if not isinstance(resource, dict) or not resource.get("enabled", True):
            continue
        state = load_state(state_dir, name, now=now)
        rows.append(resource_budget(name, resource, state, now))
    return rows


def _header(now):
    stamp = now.strftime("%A, %B ") + f"{now.day}, {now.year}"
    clock = now.strftime("%I:%M %p").lstrip("0")
    return f"Here is the TimeFence budget for {stamp} at {clock}."


def format_summary(rows, now=None):
    now = now or datetime.now()
    if not rows:
        return _header(now) + "\nNo enabled resources are configured.\n"
    lines = [_header(now), ""]
    for row in rows:
        label = row["label"]
        lines.append(row["now"])
        lines.append(_used_and_remaining(f"Today {label}", row["daily_used"], row["daily_limit"]))
        if not row["windows"]:
            lines.append(f"No allowed windows are configured for {label}.")
            lines.append("")
            continue
        for window in row["windows"]:
            name = format_window_name(window["id"])
            span = format_span(window["start"], window["end"])
            when = f" ({span})" if span else ""
            prefix = f"In the {name} window{when}, {label}"
            sentence = _used_and_remaining(prefix, window["used"], window["limit"])
            if window["current"]:
                sentence = sentence.rstrip(".") + ". This is the current window."
            lines.append(sentence)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render(app_dir, now=None):
    now = now or datetime.now()
    app_dir = Path(app_dir)
    cfg = load_config(app_dir / "config/rules.json")
    return format_summary(summarize(cfg, app_dir / "state", now=now), now=now)
