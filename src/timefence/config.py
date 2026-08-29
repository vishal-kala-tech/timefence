import json
import re
from pathlib import Path

from .policy import DAY_NAMES, parse_hhmm

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _non_negative_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a non-negative number")
    if value < 0:
        raise ValueError(f"{field} must be a non-negative number")
    return value


def _validate_window(window, field):
    if not isinstance(window, dict):
        raise ValueError(f"{field} must be an object")

    window_id = window.get("id")
    if not isinstance(window_id, str) or not window_id.strip():
        raise ValueError(f"{field} is missing a stable id")

    parse_hhmm(window.get("start"))
    parse_hhmm(window.get("end"))

    if "limit_minutes" in window and window.get("limit_minutes") is not None:
        _non_negative_number(window["limit_minutes"], f"{field}.limit_minutes")

    return window_id


def validate_day_policy(policy, field):
    if not isinstance(policy, dict):
        raise ValueError(f"{field} must be an object")

    if "daily_limit_minutes" in policy and policy.get("daily_limit_minutes") is not None:
        _non_negative_number(policy["daily_limit_minutes"], f"{field}.daily_limit_minutes")

    windows = policy.get("allowed_windows")
    if windows is None:
        raise ValueError(f"{field}.allowed_windows is required")
    if not isinstance(windows, list):
        raise ValueError(f"{field}.allowed_windows must be an array")

    seen = set()
    for index, window in enumerate(windows):
        window_id = _validate_window(window, f"{field}.allowed_windows[{index}]")
        if window_id in seen:
            raise ValueError(f"{field} has duplicate window id {window_id!r}")
        seen.add(window_id)


def validate_resource(name, resource):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Resource name must be a non-empty string")
    if not isinstance(resource, dict):
        raise ValueError(f"Resource {name!r} must be an object")

    policy = resource.get("policy")
    if not isinstance(policy, dict):
        raise ValueError(f"Resource {name!r} is missing a policy object")

    day_policies = []
    if "default" in policy:
        day_policies.append(("default", policy["default"]))
    if "weekday" in policy:
        day_policies.append(("weekday", policy["weekday"]))
    if "weekend" in policy:
        day_policies.append(("weekend", policy["weekend"]))

    days = policy.get("days")
    if days is not None:
        if not isinstance(days, dict):
            raise ValueError(f"Resource {name!r} policy.days must be an object")
        for day_name, day_policy in days.items():
            if day_name not in DAY_NAMES:
                raise ValueError(f"Resource {name!r} has unknown day {day_name!r}")
            day_policies.append((f"days.{day_name}", day_policy))

    date_overrides = policy.get("date_overrides")
    if date_overrides is not None:
        if not isinstance(date_overrides, dict):
            raise ValueError(f"Resource {name!r} policy.date_overrides must be an object")
        for date_key, day_policy in date_overrides.items():
            if not isinstance(date_key, str) or not DATE_RE.match(date_key):
                raise ValueError(f"Resource {name!r} has invalid date override {date_key!r}")
            day_policies.append((f"date_overrides.{date_key}", day_policy))

    if not day_policies:
        raise ValueError(f"Resource {name!r} has no default, day, or weekday policy")

    for label, day_policy in day_policies:
        validate_day_policy(day_policy, f"resources.{name}.policy.{label}")


def validate_config(cfg):
    if not isinstance(cfg, dict):
        raise ValueError("Unsupported or invalid config")
    if cfg.get("version") != 1:
        raise ValueError("Unsupported or invalid config")

    resources = cfg.get("resources")
    if not isinstance(resources, dict):
        raise ValueError("Unsupported or invalid config")

    interval = cfg.get("check_interval_seconds", 15)
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval < 1:
        raise ValueError("check_interval_seconds must be a positive number")

    for name, resource in resources.items():
        validate_resource(name, resource)

    return cfg


def load_config(path: Path) -> dict:
    with path.open() as f:
        cfg = json.load(f)
    return validate_config(cfg)
