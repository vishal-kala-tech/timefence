import logging
import time
from datetime import datetime
from pathlib import Path

from .config import load_config
from .notifications import show_notification
from .policy import due_warnings, evaluate, limit_seconds, limit_label, resolve_policy, resource_label
from .resources import roblox, youtube
from .usage import add_usage, load_state, mark_warning_sent

MODULES = {"roblox": roblox, "youtube": youtube}


def _now():
    return datetime.now()


def _usage_fields(policy, state, window=None):
    daily_limit = limit_seconds(policy.get("daily_limit_minutes"))
    used = int(state.get("total_usage_seconds", 0))
    parts = [f"usage={used}s", f"limit={limit_label(daily_limit)}"]
    if window:
        window_id = window.get("id")
        window_limit = limit_seconds(window.get("limit_minutes"))
        window_used = int((state.get("windows") or {}).get(window_id, {}).get("usage_seconds", 0))
        parts.extend(
            [
                f"window={window_id}",
                f"window_usage={window_used}s",
                f"window_limit={limit_label(window_limit)}",
            ]
        )
    return " ".join(parts)


def _emit_warnings(name, resource, policy, state, window, state_dir, now):
    label = resource_label(name, resource)
    for warning in due_warnings(policy, state, window=window, label=label):
        try:
            sent = show_notification("TimeFence", warning.message)
        except Exception:
            logging.exception("Notification failed for %s", name)
            continue
        if not sent:
            continue
        mark_warning_sent(state_dir, name, warning, now=now)
        logging.info("Warned %s: %s", name, warning.message)


def _tick_resource(name, resource, state_dir, interval, now):
    if not resource.get("enabled") or name not in MODULES:
        return

    mod = MODULES[name]
    policy = resolve_policy(resource, now=now)
    state = load_state(state_dir, name, now=now)
    decision = evaluate(policy, state, now=now)
    active = mod.is_active(resource)

    if not active:
        return

    if not decision.allowed:
        logging.warning(
            "Blocking %s: %s %s",
            name,
            decision.reason,
            _usage_fields(policy, state, decision.window),
        )
        mod.enforce(resource)
        return

    state = add_usage(state_dir, name, interval, window_id=decision.window_id, now=now)
    try:
        _emit_warnings(name, resource, policy, state, decision.window, state_dir, now)
    except Exception:
        logging.exception("Warning evaluation failed for %s", name)
    logging.info("%s active %s", name, _usage_fields(policy, state, decision.window))


def run(app_dir: Path):
    cfg_path = app_dir / "config/rules.json"
    state_dir = app_dir / "state"
    last_revision = None
    last_cfg = None

    while True:
        interval = 15
        try:
            try:
                cfg = load_config(cfg_path)
                last_cfg = cfg
            except Exception:
                logging.exception("Invalid config; keeping last valid configuration")
                cfg = last_cfg
                if cfg is None:
                    time.sleep(interval)
                    continue

            interval = int(cfg.get("check_interval_seconds", 15))
            if cfg.get("revision") != last_revision:
                logging.info("Loaded config revision %s", cfg.get("revision"))
                last_revision = cfg.get("revision")

            now = _now()
            for name, resource in cfg["resources"].items():
                try:
                    _tick_resource(name, resource, state_dir, interval, now)
                except Exception:
                    logging.exception("Resource %s failed", name)
        except Exception:
            logging.exception("Controller cycle failed")
        time.sleep(locals().get("interval", 15))
