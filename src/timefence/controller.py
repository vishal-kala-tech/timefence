"""The only control loop. Reloads policy, records usage, then enforces.

Each cycle:

1. Load `config/rules.json`. Invalid JSON keeps the last valid config so a
   parent typo cannot stop the agent.
2. Optionally log the frontmost browser tab (`log_browsing`). That is history, not
   a budget.
3. Screen-time tick: snapshot frontmost app, credit elapsed seconds in SQLite,
   dual-write the same seconds into the JSON usage files that status/grants
   still read.
4. Per resource: app-capture resources (`bundle_ids` or `type: app`) only
   enforce if the process is still running. They must not add usage again
   (the screen-time tick already did). YouTube/website resources still use
   the old inspect → add-interval → enforce path.
5. Refresh the local status page.

Resource adapters are chosen by `_module_for`: `module`, then resource name,
then `type`. A resource named `roblox` therefore uses `resources/roblox.py`
even when it also has `bundle_ids`. Counting still goes through screen-time;
only quit/inspect for enforcement uses that module.
"""

import logging
import time
from datetime import datetime
from pathlib import Path

from . import browse
from .activity import create_activity_monitor, usage_identity_for_activity, uses_app_capture
from .config import load_config, screen_time_settings
from .enforcement import EnforcementService
from .grants import (
    effective_daily_limit,
    effective_window_limit,
    load_grant,
)
from .identity import (
    RESOURCE_TYPE_APP,
    RESOURCE_TYPE_VIDEO_CATEGORY,
    listed_resources,
    resource_id_of,
    resource_key,
    resource_type_of,
)
from .notifications import show_block_countdown, show_notification
from . import status_page, status_server
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

# Name/type → inspect/enforce adapter. Screen-time matching does not use this;
# it keys off `bundle_ids` / `app_ids`. `website` uses the browser-tab adapter.
MODULES = {
    "roblox": roblox,
    "youtube": youtube,
    "app": app_resource,
    "website": youtube,
    "video_category": youtube,
}


def _module_for(resource, name=None):
    rtype = resource_type_of(resource)
    for key in (resource.get("module"), rtype, name):
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


def _emit_warnings(resource, policy, state, window, state_dir, now, grant=None):
    """One dialog per poll for every newly crossed threshold, then persist so we do not re-alert."""
    rtype, rid = resource_key(resource)
    label = resource_label(rid, resource)
    warnings = due_warnings(policy, state, window=window, label=label, grant=grant, now=now)
    if not warnings:
        return

    message = warning_dialog_message(warnings, label=label)
    try:
        sent = show_notification("TimeFence", message)
    except Exception:
        logging.exception("Notification failed for %s/%s", rtype, rid)
        return
    if not sent:
        return

    for warning in warnings:
        mark_warning_sent(state_dir, rtype, rid, warning, now=now)
    logging.info("Warned %s/%s: %s", rtype, rid, message)


def _poll(mod, resource):
    """Ask the adapter whether the resource is in use, and for page details.

    `inspect()` returning None means not running / not the matching tab.
    A dict can include `foreground`, `playback`, and YouTube `video` metadata.
    """
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


def _watched_log(resource, video):
    rtype, rid = resource_key(resource)
    bits = [f"Watched {rid}:", video.get("id") or "", video.get("title") or ""]
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
    """Website-only: paused video or background Chrome tab should not add seconds."""
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


def _log_browse(state_dir, interval, now, cfg=None):
    page = browse.inspect(cfg=cfg)
    if not page:
        return
    browse.note_visit(state_dir, page, interval, now=now)


def _block(resource, mod, policy, state, decision, now, grant=None, video=None, state_dir=None, enforcement=None):
    """Countdown first (best-effort), then quit/close. A failed popup still enforces."""
    rtype, rid = resource_key(resource)
    if video and state_dir is not None:
        note_video(state_dir, rtype, rid, video, now=now)
    logging.warning(
        "Blocking %s/%s: %s %s %s",
        rtype,
        rid,
        decision.reason,
        _block_fields(policy, state, decision, now, grant=grant),
        _video_fields(video),
    )
    label = resource_label(rid, resource)
    try:
        show_block_countdown("TimeFence", _block_countdown_message(label, decision.reason))
    except Exception:
        logging.exception("Block countdown failed for %s/%s", rtype, rid)
    if enforcement is not None:
        enforcement.enforce(resource)
    else:
        mod.enforce(resource)


_last_frontmost_key = None


def _log_frontmost(observation, resource_type=None, resource_id=None):
    """One SCREEN_TIME_FRONTMOST line per change. Unchanged polls stay silent."""
    global _last_frontmost_key
    front = observation.frontmost
    key = (
        (front.bundle_id if front else None),
        (front.app_name if front else None),
        bool(observation.screen_locked),
        resource_type,
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
        "SCREEN_TIME_FRONTMOST app=%s bundle_id=%s pid=%s resource_type=%s resource=%s idle_seconds=%s locked=%s",
        front.app_name or "unknown",
        front.bundle_id or "none",
        front.pid,
        resource_type or "none",
        resource_id or "none",
        int(observation.idle_seconds),
        int(observation.screen_locked),
    )


def _monitored_app_ids(cfg):
    names = []
    for resource in listed_resources(cfg):
        if resource.get("enabled", True) and uses_app_capture(resource):
            names.append(resource_id_of(resource))
    return names


def _sync_screen_time_usage(resource_type, resource_id, resource, seconds, state_dir, now, tracker):
    """Copy app-layer SQLite seconds into JSON/windows and run policy.

    UsageTracker already wrote daily_usage for the app. credit_daily=False
    so this path does not double-count screen time.
    """
    if not isinstance(resource, dict):
        state = add_usage(
            state_dir, resource_type, resource_id, seconds, now=now, credit_daily=False
        )
        logging.info(
            "%s/%s active usage=%ss (unlisted)",
            resource_type,
            resource_id,
            int(state.get("total_usage_seconds", 0)),
        )
        return state, None
    policy = resolve_policy(resource, now=now)
    window = matching_window(policy, now=now)
    window_id = window.get("id") if window else None
    state = add_usage(
        state_dir,
        resource_type,
        resource_id,
        seconds,
        window_id=window_id,
        now=now,
        credit_daily=False,
    )
    grant = load_grant(state_dir, resource_type, resource_id, now=now)
    decision = evaluate(policy, state, now=now, grant=grant)
    try:
        _emit_warnings(resource, policy, state, decision.window, state_dir, now, grant=grant)
    except Exception:
        logging.exception("Warning evaluation failed for %s/%s", resource_type, resource_id)
    if decision.reason == "daily_limit":
        day = now.date().isoformat()
        if tracker.store.record_warning(day, resource_type, resource_id, "limit_reached", triggered_at=now.replace(microsecond=0).isoformat()):
            logging.info(
                "SCREEN_TIME_LIMIT_REACHED resource_type=%s resource=%s used_seconds=%s",
                resource_type,
                resource_id,
                int(state.get("total_usage_seconds", 0)),
            )
    extra = _usage_fields(policy, state, decision.window, grant=grant, now=now)
    logging.info("%s/%s active %s", resource_type, resource_id, extra)
    return state, decision


def _tick_screen_time(cfg, settings, monitor, tracker, state_dir, now):
    """Foreground app accounting for every frontmost app, listed or not."""
    if not settings.enabled:
        return
    observation = monitor.capture(now)
    result = tracker.apply(observation, cfg, settings)
    current = None
    if observation.frontmost and observation.frontmost.bundle_id:
        current = usage_identity_for_activity(cfg, observation.resolved_activity())
    _log_frontmost(
        observation,
        current[0] if current else None,
        current[1] if current else None,
    )
    if not result.increment_seconds or not result.resource_id:
        return
    resource_type = result.resource_type or RESOURCE_TYPE_APP
    resource_id = result.resource_id
    resource = None
    for item in listed_resources(cfg):
        if resource_type_of(item) == resource_type and resource_id_of(item) == resource_id:
            resource = item
            break
    _sync_screen_time_usage(resource_type, resource_id, resource, result.increment_seconds, state_dir, now, tracker)


def _enforce_if_running(resource, state_dir, now, enforcement):
    """Block an app-capture resource that is still running after the budget is gone.

    Does not add usage. `_tick_screen_time` already counted this interval.
    """
    if not resource.get("enabled"):
        return
    rtype, rid = resource_key(resource)
    mod = _module_for(resource)
    if mod is None:
        return
    policy = resolve_policy(resource, now=now)
    state = load_state(state_dir, rtype, rid, now=now)
    grant = load_grant(state_dir, rtype, rid, now=now)
    decision = evaluate(policy, state, now=now, grant=grant)
    active, page = _poll(mod, resource)
    if not active or decision.allowed:
        return
    _block(
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


def _tick_resource(resource, state_dir, interval, now, enforcement=None):
    """Inspect → count configured interval → enforce (video categories / websites).

    Credits `interval` seconds when active. App-capture resources must not use
    this path or they would double-count screen time.
    """
    if not resource.get("enabled"):
        return
    rtype, rid = resource_key(resource)
    mod = _module_for(resource)
    if mod is None:
        return
    policy = resolve_policy(resource, now=now)
    state = load_state(state_dir, rtype, rid, now=now)
    grant = load_grant(state_dir, rtype, rid, now=now)
    decision = evaluate(policy, state, now=now, grant=grant)
    active, page = _poll(mod, resource)
    video = _video_from_page(page)

    if not active:
        return

    idle = _idle_reason(page)

    if not decision.allowed:
        _block(
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
            "%s/%s %s %s%s",
            rtype,
            rid,
            idle,
            _usage_fields(policy, state, decision.window, grant=grant, now=now),
            f" {extra}" if extra else "",
        )
        return

    if video and video.get("id") != _last_video_id(state):
        logging.info("%s", _watched_log(resource, video))

    state = add_usage(
        state_dir,
        rtype,
        rid,
        interval,
        window_id=decision.window_id,
        now=now,
        video=video,
        credit_daily=True,
    )
    try:
        _emit_warnings(resource, policy, state, decision.window, state_dir, now, grant=grant)
    except Exception:
        logging.exception("Warning evaluation failed for %s/%s", rtype, rid)
    extra = _video_fields(video)
    logging.info(
        "%s/%s active %s%s",
        rtype,
        rid,
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
    """Own the agent process until launchd stops it. Close open sessions on exit."""
    cfg_path = app_dir / "config/rules.json"
    state_dir = app_dir / "state"
    last_revision = None
    last_cfg = None
    store = SqliteUsageStore(state_dir / "screen_time.sqlite")
    tracker = UsageTracker(store)
    monitor = create_activity_monitor()
    enforcement = EnforcementService(_module_for)
    # Sessions left open after a crash/kill must not pick up the downtime as usage.
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
            # Revision log is the signal that live rules.json actually changed.
            # install.sh does not overwrite an existing file, so a missing
            # SCREEN_TIME_ENABLED line usually means the live config is old.
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
                    _log_browse(state_dir, interval, now, cfg=cfg)
                except Exception:
                    logging.exception("Browse log failed")
            if tracker is not None and monitor is not None:
                try:
                    _tick_screen_time(cfg, settings, monitor, tracker, state_dir, now)
                except Exception:
                    logging.exception("Screen-time monitor failed")
            for resource in listed_resources(cfg):
                try:
                    if settings.enabled and uses_app_capture(resource):
                        _enforce_if_running(resource, state_dir, now, enforcement)
                    elif resource_type_of(resource) == RESOURCE_TYPE_VIDEO_CATEGORY:
                        _tick_resource(resource, state_dir, interval, now, enforcement=enforcement)
                except Exception:
                    logging.exception("Resource %s/%s failed", resource_type_of(resource), resource_id_of(resource))
            try:
                _publish_status_page(app_dir, cfg, now)
            except Exception:
                logging.exception("Status page failed")
        except Exception:
            logging.exception("Controller cycle failed")
        time.sleep(locals().get("interval", 15))
