"""Load and validate `config/rules.json`. Shared by the agent and parent editor.

Reject the whole file on any schema error so a bad parent save cannot run.
`save_config` writes to a temp file then replaces, so a crash mid-write does
not leave truncated JSON.

`allowed_windows` is optional on a day policy:
- key absent → schedule unrestricted (track / daily cap only)
- `[]` → never allowed except a bonus grant
"""

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


def _positive_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a positive number")
    if value <= 0:
        raise ValueError(f"{field} must be a positive number")
    return value


def validate_warning_minutes(warnings, field, limit_minutes=None):
    if warnings is None:
        return
    if not isinstance(warnings, list):
        raise ValueError(f"{field} must be an array")
    seen = set()
    for index, value in enumerate(warnings):
        _positive_number(value, f"{field}[{index}]")
        key = float(value)
        if key in seen:
            raise ValueError(f"{field} has duplicate value {value}")
        seen.add(key)
        if limit_minutes not in (None, 0) and value > limit_minutes:
            raise ValueError(f"{field} value {value} exceeds the {limit_minutes}-minute limit")


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

    validate_warning_minutes(
        window.get("warning_minutes"),
        f"{field}.warning_minutes",
        limit_minutes=window.get("limit_minutes"),
    )

    return window_id


def validate_day_policy(policy, field):
    if not isinstance(policy, dict):
        raise ValueError(f"{field} must be an object")

    if "daily_limit_minutes" in policy and policy.get("daily_limit_minutes") is not None:
        _non_negative_number(policy["daily_limit_minutes"], f"{field}.daily_limit_minutes")

    validate_warning_minutes(
        policy.get("warning_minutes"),
        f"{field}.warning_minutes",
        limit_minutes=policy.get("daily_limit_minutes"),
    )

    windows = policy.get("allowed_windows")
    # Missing key is unrestricted; only an explicit list is validated.
    if windows is None:
        return
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

    display_name = resource.get("display_name")
    if display_name is not None and (not isinstance(display_name, str) or not display_name.strip()):
        raise ValueError(f"Resource {name!r} display_name must be a non-empty string")

    resource_type = resource.get("type")
    if resource_type is not None and (not isinstance(resource_type, str) or not resource_type.strip()):
        raise ValueError(f"Resource {name!r} type must be a non-empty string")

    for field in ("url_contains", "url_excludes", "bundle_ids", "executables"):
        values = resource.get(field)
        if values is None:
            continue
        if not isinstance(values, list) or not all(isinstance(item, str) and item for item in values):
            raise ValueError(f"Resource {name!r} {field} must be an array of non-empty strings")

    _validate_app_ids(resource.get("app_ids"), f"Resource {name!r} app_ids")
    _validate_browser_field(resource.get("browser"), f"Resource {name!r} browser")
    _validate_browser_field(resource.get("browsers"), f"Resource {name!r} browsers")

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
    """Fail the whole file. The agent keeps the last valid config if this raises."""
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

    if "log_browsing" in cfg and not isinstance(cfg.get("log_browsing"), bool):
        raise ValueError("log_browsing must be a boolean")

    if "status_page" in cfg and not isinstance(cfg.get("status_page"), bool):
        raise ValueError("status_page must be a boolean")

    if "status_port" in cfg:
        port = cfg.get("status_port")
        if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError("status_port must be an integer from 1 to 65535")

    _validate_screen_time(cfg.get("screen_time"))
    _validate_browser_field(cfg.get("browser"), "browser")
    _validate_browser_field(cfg.get("browsers"), "browsers")

    for name, resource in resources.items():
        validate_resource(name, resource)

    return cfg


def _validate_browser_field(value, field):
    if value is None:
        return
    from .browsers.matching import KNOWN_BROWSERS, normalize_browser_names

    if isinstance(value, str):
        names = normalize_browser_names(value)
        if not names:
            raise ValueError(f"{field} must be a non-empty browser name")
    elif isinstance(value, list):
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError(f"{field} must be an array of non-empty strings")
        names = normalize_browser_names(value)
        if not names:
            raise ValueError(f"{field} must be an array of non-empty strings")
    else:
        raise ValueError(f"{field} must be a browser name or an array of names")
    unknown = [name for name in names if name not in KNOWN_BROWSERS]
    if unknown:
        raise ValueError(f"{field} has unknown browser {unknown[0]!r}")


def _validate_app_ids(value, field):
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object of OS name → app ids")
    for os_name, ids in value.items():
        if not isinstance(os_name, str) or not os_name.strip():
            raise ValueError(f"{field} keys must be OS names")
        if not isinstance(ids, list) or not all(isinstance(item, str) and item for item in ids):
            raise ValueError(f"{field}.{os_name} must be an array of non-empty strings")


def _validate_screen_time(screen_time):
    if screen_time is None:
        return
    if not isinstance(screen_time, dict):
        raise ValueError("screen_time must be an object")
    if "enabled" in screen_time and not isinstance(screen_time.get("enabled"), bool):
        raise ValueError("screen_time.enabled must be a boolean")
    if "poll_interval_seconds" in screen_time:
        _positive_number(screen_time["poll_interval_seconds"], "screen_time.poll_interval_seconds")
    if "idle_threshold_seconds" in screen_time:
        _non_negative_number(screen_time["idle_threshold_seconds"], "screen_time.idle_threshold_seconds")
    if "max_countable_interval_seconds" in screen_time:
        _positive_number(
            screen_time["max_countable_interval_seconds"],
            "screen_time.max_countable_interval_seconds",
        )


def screen_time_settings(cfg):
    """Map `screen_time` (and legacy `check_interval_seconds`) onto ScreenTimeSettings."""
    from .tracking.usage_tracker import DEFAULT_IDLE_THRESHOLD_SECONDS, MAX_COUNTABLE_INTERVAL_SECONDS, ScreenTimeSettings

    raw = cfg.get("screen_time") if isinstance(cfg, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    poll = raw.get("poll_interval_seconds")
    if poll is None:
        poll = (cfg or {}).get("check_interval_seconds", 15)
    return ScreenTimeSettings(
        enabled=bool(raw.get("enabled", True)),
        poll_interval_seconds=int(poll),
        idle_threshold_seconds=float(raw.get("idle_threshold_seconds", DEFAULT_IDLE_THRESHOLD_SECONDS)),
        max_countable_interval_seconds=float(
            raw.get("max_countable_interval_seconds", MAX_COUNTABLE_INTERVAL_SECONDS)
        ),
    )


def load_config(path: Path) -> dict:
    with path.open() as f:
        cfg = json.load(f)
    return validate_config(cfg)


def save_config(path: Path, cfg: dict) -> dict:
    """Validate, then atomically replace the live rules file."""
    cfg = validate_config(cfg)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return cfg
