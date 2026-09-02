import logging
import time
from datetime import datetime
from pathlib import Path

from . import browse
from .activity import MacOSActivityMonitor, find_resource_by_bundle_id, uses_app_capture
from .config import load_config, screen_time_settings
from .enforcement import EnforcementService
from .grants import (
    effective_daily_limit,
    effective_window_limit,
    load_grant,
)
from .notifications import show_block_countdown, show_notification
from . import status_page, status_server
from .policy import (
    DAY_NAMES,
    due_warnings,
    evaluate,
    limit_label,
    matching_window,
    resolve_policy,
    resource_label,
    warning_dialog_message,
)
from .resources import app as app_resource
from .resources import roblox, youtube
from .tracking import SqliteUsageStore, UsageTracker
from .usage import add_usage, load_state, mark_warning_sent, note_video

MODULES = {
    "roblox": roblox,
    "youtube": youtube,
    "app": app_resource,
    "website": youtube,
}


def _module_for(name, resource):
    for key in (resource.get("module"), name, resource.get("type")):
        if isinstance(key, str) and key in MODULES:
            return MODULES[key]
    return None


def _now():
    return datetime.now()


def _window_summary(policy):
    windows = policy.get("allowed_windows") or []
    if not windows:
        return "none"
    return ",".join(
        f"{window.get('id', '?')}={window.get('start')}-{window.get('end')}"
        for window in windows
    )


def _block_fields(policy, state, decision, now, grant=None):
    parts = [
        f"now={now.strftime('%H:%M')}",
        f"day={DAY_NAMES[now.weekday()]}",
        f"windows={_window_summary(policy)}",
        _usage_fields(policy, state, decision.window, grant=grant, now=now),
    ]
    if decision.reason == "outside_window":
        parts.append("not in any allowed window")
    elif decision.reason == "daily_limit":
        parts.append("daily usage cap reached")
    elif decision.reason == "window_limit":
        parts.append("window usage cap reached")
    return " ".join(parts)


def _usage_fields(policy, state, window=None, grant=None, now=None):
    daily_limit = effective_daily_limit(policy, grant, now=now)
    used = int(state.get("total_usage_seconds", 0))
    parts = [f"usage={used}s", f"limit={limit_label(daily_limit)}"]
    if window:
        window_id = window.get("id")
        window_limit = effective_window_limit(window, grant, now=now)
        window_used = int((state.get("windows") or {}).get(window_id, {}).get("usage_seconds", 0))
        parts.extend(
            [
                f"window={window_id}",
                f"window_usage={window_used}s",
                f"window_limit={limit_label(window_limit)}",
            ]
        )
    return " ".join(parts)


def _emit_warnings(name, resource, policy, state, window, state_dir, now, grant=None):
    label = resource_label(name, resource)
    warnings = due_warnings(policy, state, window=window, label=label, grant=grant, now=now)
    if not warnings:
        return

    message = warning_dialog_message(warnings, label=label)
    try:
        sent = show_notification("TimeFence", message)
    except Exception:
        logging.exception("Notification failed for %s", name)
        return
    if not sent:
        return

    for warning in warnings:
        mark_warning_sent(state_dir, name, warning, now=now)
    logging.info("Warned %s: %s", name, message)


def _poll(mod, resource):
    inspect = getattr(mod, "inspect", None)
    if callable(inspect):
        page = inspect(resource)
        if isinstance(page, dict):
            return True, page
        if page is None:
            return False, None
    return bool(mod.is_active(resource)), None


def _video_from_page(page):
    if not isinstance(page, dict):
        return None
    video = page.get("video")
    if isinstance(video, dict) and video.get("id"):
        return video
    return None


def _video_fields(video):
    if not video:
        return ""
    title = video.get("title") or ""
    channel = video.get("channel") or ""
    parts = [f"video={video.get('id')}"]
    if title:
        parts.append(f"title={title!r}")
    if channel:
        parts.append(f"channel={channel!r}")
    return " ".join(parts)


def _watched_log(name, video):
    bits = [f"Watched {name}:", video.get("id") or "", video.get("title") or ""]
    message = " ".join(bit for bit in bits if bit)
    channel = video.get("channel") or ""
    if channel:
        message += f" ({channel})"
    return message


def _last_video_id(state):
    videos = state.get("videos") or []
    if not videos:
        return None
    return videos[-1].get("id")


def _idle_reason(page):
    if not isinstance(page, dict):
        return None
    if page.get("playback") == "paused":
        return "paused"
    if page.get("foreground") is False:
        return "background"
    return None


def _block_countdown_message(label, reason):
    if reason == "outside_window":
        return f"{label} is not allowed right now."
    if reason == "window_limit":
        return f"{label} has no time remaining in this window."
    return f"{label} has no time remaining today."


def _log_browse(state_dir, interval, now):
    page = browse.inspect()
    if not page:
        return
    browse.note_visit(state_dir, page, interval, now=now)


def _block(name, resource, mod, policy, state, decision, now, grant=None, video=None, state_dir=None, enforcement=None):
    if video and state_dir is not None:
        note_video(state_dir, name, video, now=now)
    logging.warning(
        "Blocking %s: %s %s %s",
        name,
        decision.reason,
        _block_fields(policy, state, decision, now, grant=grant),
        _video_fields(video),
    )
    label = resource_label(name, resource)
    try:
        show_block_countdown("TimeFence", _block_countdown_message(label, decision.reason))
    except Exception:
        logging.exception("Block countdown failed for %s", name)
    if enforcement is not None:
        enforcement.enforce(name, resource)
    else:
        mod.enforce(resource)


_last_frontmost_key = None


def _log_frontmost(observation, resource_id=None):
    global _last_frontmost_key
    front = observation.frontmost
    key = (
        (front.bundle_id if front else None),
        (front.app_name if front else None),
        bool(observation.screen_locked),
        resource_id,
    )
    if key == _last_frontmost_key:
        return
    _last_frontmost_key = key
    if front is None:
        logging.info(
            "SCREEN_TIME_FRONTMOST app=none bundle_id=none idle_seconds=%s locked=%s",
            int(observation.idle_seconds),
            int(observation.screen_locked),
        )
        return
    logging.info(
        "SCREEN_TIME_FRONTMOST app=%s bundle_id=%s pid=%s resource=%s idle_seconds=%s locked=%s",
        front.app_name or "unknown",
        front.bundle_id or "none",
        front.pid,
        resource_id or "none",
        int(observation.idle_seconds),
        int(observation.screen_locked),
    )


def _monitored_app_ids(cfg):
    names = []
    for name, resource in (cfg.get("resources") or {}).items():
        if isinstance(resource, dict) and resource.get("enabled", True) and uses_app_capture(resource):
            names.append(name)
    return names


def _sync_screen_time_usage(name, resource, seconds, state_dir, now, tracker):
    policy = resolve_policy(resource, now=now)
    window = matching_window(policy, now=now)
    window_id = window.get("id") if window else None
    state = add_usage(state_dir, name, seconds, window_id=window_id, now=now)
    grant = load_grant(state_dir, name, now=now)
    decision = evaluate(policy, state, now=now, grant=grant)
    try:
        _emit_warnings(name, resource, policy, state, decision.window, state_dir, now, grant=grant)
    except Exception:
        logging.exception("Warning evaluation failed for %s", name)
    if decision.reason == "daily_limit":
        day = now.date().isoformat()
        if tracker.store.record_warning(day, name, "limit_reached"):
            logging.info(
                "SCREEN_TIME_LIMIT_REACHED resource=%s used_seconds=%s",
                name,
                int(state.get("total_usage_seconds", 0)),
            )
    extra = _usage_fields(policy, state, decision.window, grant=grant, now=now)
    logging.info("%s active %s", name, extra)
    return state, decision


def _tick_screen_time(cfg, settings, monitor, tracker, state_dir, now):
    if not settings.enabled or not _monitored_app_ids(cfg):
        return
    observation = monitor.capture(now)
    result = tracker.apply(observation, cfg.get("resources") or {}, settings)
    current = None
    if observation.frontmost and observation.frontmost.bundle_id:
        match = find_resource_by_bundle_id(cfg.get("resources") or {}, observation.frontmost.bundle_id)
        current = match[0] if match else None
    _log_frontmost(observation, current)
    if not result.increment_seconds or not result.resource_id:
        return
    name = result.resource_id
    resource = (cfg.get("resources") or {}).get(name)
    if not isinstance(resource, dict):
        return
    _sync_screen_time_usage(name, resource, result.increment_seconds, state_dir, now, tracker)


def _enforce_if_running(name, resource, state_dir, now, enforcement):
    if not resource.get("enabled"):
        return
    mod = _module_for(name, resource)
    if mod is None:
        return
    policy = resolve_policy(resource, now=now)
    state = load_state(state_dir, name, now=now)
    grant = load_grant(state_dir, name, now=now)
    decision = evaluate(policy, state, now=now, grant=grant)
    active, page = _poll(mod, resource)
    if not active or decision.allowed:
        return
    _block(
        name,
        resource,
        mod,
        policy,
        state,
        decision,
        now,
        grant=grant,
        video=_video_from_page(page),
        state_dir=state_dir,
        enforcement=enforcement,
    )


def _tick_resource(name, resource, state_dir, interval, now, enforcement=None):
    if not resource.get("enabled"):
        return
    mod = _module_for(name, resource)
    if mod is None:
        return
    policy = resolve_policy(resource, now=now)
    state = load_state(state_dir, name, now=now)
    grant = load_grant(state_dir, name, now=now)
    decision = evaluate(policy, state, now=now, grant=grant)
    active, page = _poll(mod, resource)
    video = _video_from_page(page)

    if not active:
        return

    idle = _idle_reason(page)

    if not decision.allowed:
        _block(
            name,
            resource,
            mod,
            policy,
            state,
            decision,
            now,
            grant=grant,
            video=video,
            state_dir=state_dir,
            enforcement=enforcement,
        )
        return

    if idle:
        extra = _video_fields(video)
        logging.info(
            "%s %s %s%s",
            name,
            idle,
            _usage_fields(policy, state, decision.window, grant=grant, now=now),
            f" {extra}" if extra else "",
        )
        return

    if video and video.get("id") != _last_video_id(state):
        logging.info("%s", _watched_log(name, video))

    state = add_usage(
        state_dir, name, interval, window_id=decision.window_id, now=now, video=video
    )
    try:
        _emit_warnings(name, resource, policy, state, decision.window, state_dir, now, grant=grant)
    except Exception:
        logging.exception("Warning evaluation failed for %s", name)
    extra = _video_fields(video)
    logging.info(
        "%s active %s%s",
        name,
        _usage_fields(policy, state, decision.window, grant=grant, now=now),
        f" {extra}" if extra else "",
    )


def _publish_status_page(app_dir, cfg, now):
    if not cfg.get("status_page", True):
        status_server.stop()
        return
    try:
        status_page.write_html(app_dir, now=now, cfg=cfg)
    except Exception:
        logging.exception("Status page write failed")
    port = int(cfg.get("status_port", status_page.DEFAULT_STATUS_PORT))
    status_server.ensure(app_dir, port)


def run(app_dir: Path):
    cfg_path = app_dir / "config/rules.json"
    state_dir = app_dir / "state"
    last_revision = None
    last_cfg = None
    store = SqliteUsageStore(state_dir / "screen_time.sqlite")
    tracker = UsageTracker(store)
    monitor = MacOSActivityMonitor()
    enforcement = EnforcementService(_module_for)
    tracker.close_orphaned_sessions()

    try:
        _run_loop(
            app_dir,
            cfg_path,
            state_dir,
            last_revision,
            last_cfg,
            monitor=monitor,
            tracker=tracker,
            enforcement=enforcement,
        )
    finally:
        try:
            tracker.close()
        except Exception:
            logging.exception("Failed to close screen-time sessions")
        status_server.stop()


def _run_loop(app_dir, cfg_path, state_dir, last_revision, last_cfg, monitor=None, tracker=None, enforcement=None):
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

            settings = screen_time_settings(cfg)
            interval = int(settings.poll_interval_seconds or cfg.get("check_interval_seconds", 15))
            if cfg.get("revision") != last_revision:
                logging.info("Loaded config revision %s", cfg.get("revision"))
                if settings.enabled:
                    logging.info(
                        "SCREEN_TIME_ENABLED poll_interval_seconds=%s idle_threshold_seconds=%s apps=%s",
                        settings.poll_interval_seconds,
                        int(settings.idle_threshold_seconds),
                        ",".join(_monitored_app_ids(cfg)) or "none",
                    )
                last_revision = cfg.get("revision")

            now = _now()
            if cfg.get("log_browsing", True):
                try:
                    _log_browse(state_dir, interval, now)
                except Exception:
                    logging.exception("Browse log failed")
            if tracker is not None and monitor is not None:
                try:
                    _tick_screen_time(cfg, settings, monitor, tracker, state_dir, now)
                except Exception:
                    logging.exception("Screen-time monitor failed")
            for name, resource in cfg["resources"].items():
                try:
                    if settings.enabled and uses_app_capture(resource):
                        _enforce_if_running(name, resource, state_dir, now, enforcement)
                    else:
                        _tick_resource(name, resource, state_dir, interval, now, enforcement=enforcement)
                except Exception:
                    logging.exception("Resource %s failed", name)
            try:
                _publish_status_page(app_dir, cfg, now)
            except Exception:
                logging.exception("Status page failed")
        except Exception:
            logging.exception("Controller cycle failed")
        time.sleep(locals().get("interval", 15))
