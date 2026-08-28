import json
from pathlib import Path

ALWAYS_WINDOW = [{"start": "00:00", "end": "24:00"}]


def make_policy(daily_limit_minutes=30, allowed_windows=None):
    return {
        "daily_limit_minutes": daily_limit_minutes,
        "allowed_windows": ALWAYS_WINDOW if allowed_windows is None else allowed_windows,
    }


def make_resource(enabled=True, weekday=None, weekend=None, **extra):
    resource = {
        "enabled": enabled,
        "policy": {
            "weekday": weekday or make_policy(),
            "weekend": weekend or make_policy(daily_limit_minutes=90),
        },
    }
    resource.update(extra)
    return resource


def make_config(resources=None, revision=1, check_interval_seconds=15, version=1):
    return {
        "version": version,
        "revision": revision,
        "check_interval_seconds": check_interval_seconds,
        "resources": resources if resources is not None else {"roblox": make_resource()},
    }


def write_rules(app_dir: Path, config: dict) -> Path:
    path = app_dir / "config" / "rules.json"
    path.write_text(json.dumps(config, indent=2))
    return path
