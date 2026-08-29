import json
from pathlib import Path


def make_window(window_id="all_day", start="00:00", end="24:00", limit_minutes=None, warning_minutes=None):
    window = {"id": window_id, "start": start, "end": end}
    if limit_minutes is not None:
        window["limit_minutes"] = limit_minutes
    if warning_minutes is not None:
        window["warning_minutes"] = warning_minutes
    return window


def make_day_policy(daily_limit_minutes=30, allowed_windows=None, warning_minutes=None):
    policy = {
        "daily_limit_minutes": daily_limit_minutes,
        "allowed_windows": [make_window()] if allowed_windows is None else allowed_windows,
    }
    if warning_minutes is not None:
        policy["warning_minutes"] = warning_minutes
    return policy


def make_policy(default=None, days=None, date_overrides=None, weekday=None, weekend=None):
    policy = {}
    if default is not None or (weekday is None and weekend is None):
        policy["default"] = default or make_day_policy()
    if days:
        policy["days"] = days
    if date_overrides:
        policy["date_overrides"] = date_overrides
    if weekday is not None:
        policy["weekday"] = weekday
    if weekend is not None:
        policy["weekend"] = weekend
    return policy


def make_resource(enabled=True, default=None, days=None, date_overrides=None, weekday=None, weekend=None, **extra):
    resource = {
        "enabled": enabled,
        "policy": make_policy(
            default=default,
            days=days,
            date_overrides=date_overrides,
            weekday=weekday,
            weekend=weekend,
        ),
    }
    resource.update(extra)
    return resource


def make_config(resources=None, revision=1, check_interval_seconds=15, version=1, log_browsing=None):
    cfg = {
        "version": version,
        "revision": revision,
        "check_interval_seconds": check_interval_seconds,
        "resources": resources if resources is not None else {"roblox": make_resource()},
    }
    if log_browsing is not None:
        cfg["log_browsing"] = log_browsing
    return cfg


def write_rules(app_dir: Path, config: dict) -> Path:
    path = app_dir / "config" / "rules.json"
    path.write_text(json.dumps(config, indent=2))
    return path
