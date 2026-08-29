import logging
import time
from datetime import datetime
from pathlib import Path

from . import browse
from .config import load_config
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
    resolve_policy,
    resource_label,
    warning_dialog_message,
)
from .resources import roblox, youtube
from .usage import add_usage, load_state, mark_warning_sent, note_video

MODULES = {
    "roblox": roblox,
    "youtube": youtube,
    "app": roblox,
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


def _tick_resource(name, resource, state_dir, interval, now):
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
        if video:
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
        mod.enforce(resource)
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

    try:
        _run_loop(app_dir, cfg_path, state_dir, last_revision, last_cfg)
    finally:
        status_server.stop()


def _run_loop(app_dir, cfg_path, state_dir, last_revision, last_cfg):
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
            if cfg.get("log_browsing", True):
                try:
                    _log_browse(state_dir, interval, now)
                except Exception:
                    logging.exception("Browse log failed")
            for name, resource in cfg["resources"].items():
                try:
                    _tick_resource(name, resource, state_dir, interval, now)
                except Exception:
                    logging.exception("Resource %s failed", name)
            try:
                _publish_status_page(app_dir, cfg, now)
            except Exception:
                logging.exception("Status page failed")
        except Exception:
            logging.exception("Controller cycle failed")
        time.sleep(locals().get("interval", 15))
