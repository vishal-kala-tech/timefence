"""Parent activity report for one local calendar day.

Reads SQLite (daily totals, sessions, visits, watches) and overlays leftover
JSON so days from before those tables still appear. Does not enforce policy.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

from .browse import display_host, load_browse_state, top_sites
from .budget import format_clock, format_span, format_time_of_day, format_window_name
from .budget import summarize as budget_summarize
from .config import load_config
from .history import format_summary, summarize
from .identity import (
    RESOURCE_TYPE_APP,
    RESOURCE_TYPE_VIDEO_CATEGORY,
    RESOURCE_TYPE_WEBSITE,
    YOUTUBE_SHORTS_RESOURCE_ID,
    YOUTUBE_VIDEOS_RESOURCE_ID,
    default_display_name,
    listed_resources,
    resource_id_of,
    resource_key,
    resource_type_of,
)
from .policy import parse_hhmm, resource_label
from .tracking.sqlite_usage_store import SqliteUsageStore
from .usage import load_state


def _today(now=None):
    if isinstance(now, datetime):
        return now.date()
    if isinstance(now, date):
        return now
    return date.today()


def parse_report_date(value, now=None):
    """YYYY-MM-DD, or today. Future dates clamp to today."""
    today = _today(now)
    if value in (None, ""):
        return today
    try:
        day = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Date must be YYYY-MM-DD") from exc
    if day > today:
        return today
    return day


def _day_heading(day, today):
    stamp = day.strftime("%A, %B ") + f"{day.day}, {day.year}"
    if day == today:
        return f"Today · {stamp}"
    if day == today - timedelta(days=1):
        return f"Yesterday · {stamp}"
    return stamp


def _short_label(day):
    return day.strftime("%A, %b ") + str(day.day)


def compact_clock(seconds):
    """Short parent-dashboard durations: 2h 06m, 41m, 50s."""
    seconds = max(0, int(seconds or 0))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    return f"{secs}s"


def _report_now(day, today, now):
    if isinstance(now, datetime):
        if now.date() == day:
            return now
        return datetime.combine(day, now.time())
    if day == today:
        return datetime.now()
    return datetime.combine(day, datetime.min.time())


def _local_naive(value):
    """Parse ISO/datetime to naive local time so live tz-aware sessions compare safely."""
    if isinstance(value, datetime):
        stamp = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            stamp = datetime.fromisoformat(text)
        except ValueError:
            return None
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone().replace(tzinfo=None)
    return stamp.replace(microsecond=0)


def _store(state_dir):
    return SqliteUsageStore(Path(state_dir) / "screen_time.sqlite")


def _label_for(resource_type, resource_id, cfg, names=None):
    names = names or {}
    for resource in listed_resources(cfg):
        if resource_type_of(resource) == resource_type and resource_id_of(resource) == resource_id:
            return resource_label(resource_id, resource)
    key = (str(resource_type), str(resource_id).lower())
    if key in names:
        return names[key]
    row = names.get(str(resource_id).lower())
    if row:
        return row
    return default_display_name(resource_type, resource_id)


def _format_clock_iso(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return format_time_of_day(stamp.strftime("%H:%M"))


def _session_payload(row):
    started = _format_clock_iso(row.started_at)
    ended = _format_clock_iso(row.ended_at)
    open_row = row.ended_at in (None, "")
    if started and ended and not open_row:
        when = f"{started} – {ended}"
    elif started and open_row:
        when = f"{started} – still active"
    elif started:
        when = f"At {started}"
    else:
        when = "During the day"
    return {
        "started_at": row.started_at,
        "ended_at": row.ended_at,
        "open": open_row,
        "seconds": int(row.duration_seconds or 0),
        "seconds_label": format_clock(row.duration_seconds),
        "when_label": when,
        "identifier": row.identifier or "",
    }


def _visit_payload(item):
    host = display_host(item.get("host"))
    start = item.get("first_seen") or ""
    end = item.get("last_seen") or ""
    start_label = None
    end_label = None
    try:
        start_label = format_time_of_day(f"{int(str(start).split(':')[0]):02d}:{int(str(start).split(':')[1]):02d}")
    except (ValueError, IndexError, TypeError):
        start_label = None
    try:
        end_label = format_time_of_day(f"{int(str(end).split(':')[0]):02d}:{int(str(end).split(':')[1]):02d}")
    except (ValueError, IndexError, TypeError):
        end_label = None
    if start_label and end_label and start_label != end_label:
        when = f"{start_label} – {end_label}"
    elif start_label:
        when = f"At {start_label}"
    else:
        when = "During the day"
    return {
        "host": host,
        "url": item.get("url") or "",
        "title": item.get("title") or "",
        "resource_type": item.get("resource_type") or RESOURCE_TYPE_WEBSITE,
        "resource_id": item.get("resource_id") or host,
        "display_name": item.get("display_name") or host,
        "browser_resource_id": item.get("browser_resource_id") or "",
        "browser_name": item.get("browser_name") or item.get("browser") or "",
        "seconds": int(item.get("usage_seconds") or 0),
        "seconds_label": format_clock(item.get("usage_seconds")),
        "first_seen": start,
        "last_seen": end,
        "when_label": when,
    }


def _video_payload(item):
    resource_id = item.get("resource_id") or ""
    return {
        "resource_type": item.get("resource_type") or RESOURCE_TYPE_VIDEO_CATEGORY,
        "resource_id": resource_id,
        "video_id": item.get("video_id") or item.get("id") or "",
        "id": item.get("video_id") or item.get("id") or "",
        "title": item.get("title") or "",
        "channel": item.get("channel") or "",
        "url": item.get("url") or "",
        "seconds": int(item.get("usage_seconds") or 0),
        "seconds_label": format_clock(item.get("usage_seconds")),
        "first_seen": item.get("first_seen") or "",
        "last_seen": item.get("last_seen") or "",
    }


def _daily_seconds(state_dir, usage_date, store):
    """Map (resource_type, resource_id) → seconds. App rows are screen time."""
    rows = {}
    for item in store.get_all_daily(usage_date):
        rows[(item.resource_type, item.resource_id)] = int(item.total_active_seconds or 0)
    return rows


def _app_rows(cfg, daily, sessions_by_key, windows_by_key, names=None):
    apps = []
    for (resource_type, resource_id), seconds in daily.items():
        if resource_type != RESOURCE_TYPE_APP:
            continue
        sessions = sessions_by_key.get((resource_type, resource_id)) or []
        if not seconds and not sessions:
            continue
        windows = [
            {
                "id": window_id,
                "label": format_window_name(window_id),
                "seconds": secs,
                "seconds_label": format_clock(secs),
            }
            for window_id, secs in sorted((windows_by_key.get((resource_type, resource_id)) or {}).items())
            if secs
        ]
        display = _label_for(resource_type, resource_id, cfg, names=names)
        apps.append(
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "display_name": display,
                "id": resource_id,
                "label": display,
                "seconds": int(seconds or 0),
                "seconds_label": format_clock(seconds),
                "seconds_compact": compact_clock(seconds),
                "session_count": len(sessions),
                "sessions": sessions,
                "windows": windows,
            }
        )
    apps.sort(key=lambda item: (-item["seconds"], item["label"].lower()))
    return apps


def _current_activity(apps, visits, is_today, report_now):
    if not is_today:
        return None
    for app in apps:
        for session in app.get("sessions") or []:
            if not session.get("open"):
                continue
            seconds = int(session.get("seconds") or 0)
            started = _local_naive(session.get("started_at"))
            now = _local_naive(report_now)
            if started and now:
                elapsed = int((now - started).total_seconds())
                if elapsed > seconds:
                    seconds = elapsed
            detail = ""
            if "chrome" in str(app.get("resource_id") or "").lower() or "safari" in str(app.get("resource_id") or "").lower():
                if visits:
                    latest = max(visits, key=lambda item: str(item.get("last_seen") or ""))
                    detail = latest.get("display_name") or latest.get("host") or ""
            return {
                "label": app["label"],
                "detail": detail,
                "seconds": seconds,
                "seconds_label": format_clock(seconds),
                "compact_label": compact_clock(seconds),
            }
    return None


def _budget_rows(cfg, state_dir, report_now, names=None):
    rows = []
    for row in budget_summarize(cfg, state_dir, now=report_now):
        limit = int(row.get("daily_limit") or 0)
        used = int(row.get("daily_used") or 0)
        remaining = row.get("daily_remaining")
        if not limit:
            status = "unlimited"
            percent = 0
        else:
            percent = min(100, int(round(100 * used / limit))) if limit else 0
            if remaining == 0:
                status = "blocked"
            elif percent >= 80:
                status = "warning"
            else:
                status = "ok"
        rows.append(
            {
                "resource_type": row["resource_type"],
                "resource_id": row["resource_id"],
                "display_name": row["label"],
                "id": row["resource_id"],
                "label": row["label"],
                "used_seconds": used,
                "limit_seconds": limit,
                "remaining_seconds": remaining,
                "used_compact": compact_clock(used),
                "limit_compact": compact_clock(limit) if limit else "No cap",
                "ratio_label": (
                    f"{compact_clock(used)} / {limit // 60} min"
                    if limit and used < 60
                    else f"{used // 60} / {limit // 60} min"
                    if limit
                    else compact_clock(used)
                ),
                "remaining_compact": compact_clock(remaining) if remaining is not None else "",
                "remaining_label": (
                    "No time remaining"
                    if remaining == 0
                    else f"{compact_clock(remaining)} remaining"
                    if remaining is not None
                    else "No cap"
                ),
                "percent": percent,
                "status": status,
                "bonus": row.get("bonus"),
                "allowed": row["allowed"],
                "windows": row.get("windows") or [],
            }
        )
    return rows


def _limits_payload(rows):
    return [row for row in rows if row["limit_seconds"] or row.get("bonus")]


def _is_all_day_window(window):
    return window.get("start") == "00:00" and window.get("end") in ("24:00", "00:00")


def _next_rule(limits, report_now):
    for row in limits:
        for window in row.get("windows") or []:
            if window.get("current") and not _is_all_day_window(window):
                end = format_time_of_day(window.get("end"))
                return {
                    "title": row["label"],
                    "detail": f"Allowed until {end}",
                    "span": format_span(window.get("start"), window.get("end")),
                }
    current = report_now.hour * 60 + report_now.minute
    upcoming = []
    for row in limits:
        for window in row.get("windows") or []:
            if _is_all_day_window(window):
                continue
            try:
                start = parse_hhmm(window.get("start"))
            except (TypeError, ValueError):
                continue
            if start > current:
                upcoming.append((start, row, window))
    if not upcoming:
        return None
    _start, row, window = sorted(upcoming, key=lambda item: item[0])[0]
    span = format_span(window.get("start"), window.get("end"))
    return {
        "title": f"{row['label']} available",
        "detail": span or format_time_of_day(window.get("start")),
        "span": span,
    }


def _daily_summary(apps, hosts, videos, limits, is_today):
    sentences = []
    if apps:
        top = apps[0]
        sentences.append(
            f"Most computer time was spent in {top['label']} ({compact_clock(top['seconds'])})."
        )
        if len(apps) > 1:
            second = apps[1]
            sentences.append(
                f"{second['label']} was next at {compact_clock(second['seconds'])}."
            )
    if hosts:
        site = hosts[0]
        chrome = next(
            (
                app
                for app in apps
                if "chrome" in str(app.get("resource_id") or "").lower()
                or "safari" in str(app.get("resource_id") or "").lower()
            ),
            None,
        )
        if chrome:
            sentences.append(
                f"{chrome['label']} was used for {compact_clock(chrome['seconds'])}, primarily on {site['host']}."
            )
        else:
            sentences.append(
                f"The most visited site was {site['host']} ({compact_clock(site['seconds'])})."
            )
    video_seconds = sum(group["seconds"] for group in videos)
    if video_seconds:
        sentences.append(f"YouTube usage was {compact_clock(video_seconds)}.")
    if is_today:
        for row in limits:
            if row["status"] == "blocked":
                sentences.append(f"{row['label']} has no time remaining today.")
                break
            if row["status"] == "warning":
                sentences.append(f"{row['label']} is close to its limit.")
                break
    if not sentences:
        return "No activity was recorded on this day."
    return " ".join(sentences[:4])


def day_report(app_dir, date=None, now=None):
    """Structured parent activity for one day, plus prev/next calendar dates."""
    app_dir = Path(app_dir)
    state_dir = app_dir / "state"
    today = _today(now)
    day = parse_report_date(date, now=today)
    usage_date = day.isoformat()
    cfg_path = app_dir / "config" / "rules.json"
    cfg = load_config(cfg_path) if cfg_path.exists() else {}
    store = _store(state_dir)
    names = {
        (row["resource_type"], str(row["resource_id"]).lower()): row["display_name"]
        for row in store.list_resources()
    }

    daily = _daily_seconds(state_dir, usage_date, store)
    sessions_by_key = {}
    for row in store.get_sessions_on_date(usage_date):
        sessions_by_key.setdefault((row.resource_type, row.resource_id), []).append(_session_payload(row))
    windows_by_key = store.get_all_windows_for_date(usage_date)
    apps = _app_rows(cfg, daily, sessions_by_key, windows_by_key, names=names)
    app_seconds = sum(item["seconds"] for item in apps)

    browse_state = load_browse_state(state_dir, now=day)
    visits = [_visit_payload(item) for item in browse_state.get("visits") or []]
    hosts = [
        {
            "resource_type": RESOURCE_TYPE_WEBSITE,
            "resource_id": item["host"],
            "display_name": names.get((RESOURCE_TYPE_WEBSITE, item["host"].lower())) or item["host"],
            "host": item["host"],
            "seconds": int(item["seconds"] or 0),
            "seconds_label": format_clock(item["seconds"]),
            "seconds_compact": compact_clock(item["seconds"]),
            "visits": int(item["visits"] or 0),
            "title": item.get("title") or "",
        }
        for item in top_sites(state_dir, now=day, limit=20)
    ]
    site_seconds = sum(item["seconds"] for item in visits)

    video_groups = []
    video_seconds = 0
    video_count = 0
    for resource_type, resource_id in (
        (RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_VIDEOS_RESOURCE_ID),
        (RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_SHORTS_RESOURCE_ID),
    ):
        items = [
            _video_payload({**item, "resource_type": resource_type, "resource_id": resource_id})
            for item in load_state(state_dir, resource_type, resource_id, now=day).get("videos") or []
        ]
        total = sum(item["seconds"] for item in items)
        video_seconds += total
        video_count += len(items)
        if items:
            display = _label_for(resource_type, resource_id, cfg, names=names)
            video_groups.append(
                {
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "display_name": display,
                    "id": resource_id,
                    "label": display,
                    "seconds": total,
                    "seconds_label": format_clock(total),
                    "seconds_compact": compact_clock(total),
                    "items": items,
                }
            )

    has_data = bool(app_seconds or site_seconds or video_count or visits or any(item["sessions"] for item in apps))
    report_now = _report_now(day, today, now)
    budgets = _budget_rows(cfg, state_dir, report_now, names=names)
    limits = _limits_payload(budgets)
    by_key = {(row["resource_type"], row["resource_id"]): row for row in budgets}
    for app in apps:
        row = by_key.get((app["resource_type"], app["resource_id"]))
        if row and row.get("limit_seconds"):
            app["has_limit"] = True
            app["remaining_compact"] = row.get("remaining_compact") or compact_clock(row.get("remaining_seconds") or 0)
            app["limit_status"] = row.get("status")
        else:
            app["has_limit"] = False
    for group in video_groups:
        row = by_key.get((group["resource_type"], group["resource_id"]))
        if row and row.get("limit_seconds"):
            group["has_limit"] = True
            group["remaining_compact"] = row.get("remaining_compact") or compact_clock(row.get("remaining_seconds") or 0)
            group["limit_status"] = row.get("status")
        else:
            group["has_limit"] = False
    current = _current_activity(apps, visits, day == today, report_now)
    next_rule = _next_rule(budgets, report_now) if day == today else None
    daily_summary = _daily_summary(apps, hosts, video_groups, limits, day == today)

    narrative = format_summary(summarize(cfg, state_dir, now=datetime.combine(day, datetime.min.time())), now=datetime.combine(day, datetime.min.time()))
    if app_seconds:
        top = apps[0]
        app_word = "app" if len(apps) == 1 else "apps"
        verb = "was" if len(apps) == 1 else "were"
        app_line = (
            f"{len(apps)} {app_word} {verb} in the foreground, for a total of {format_clock(app_seconds)}. "
            f"Most of that was {top['label']}."
        )
    else:
        app_line = "No app screen time was recorded."

    return {
        "date": usage_date,
        "today": today.isoformat(),
        "label": _day_heading(day, today),
        "short_label": _short_label(day),
        "is_today": day == today,
        "prev_date": (day - timedelta(days=1)).isoformat(),
        "next_date": None if day == today else (day + timedelta(days=1)).isoformat(),
        "has_data": has_data,
        "summary": {
            "app_seconds": app_seconds,
            "app_label": format_clock(app_seconds),
            "app_count": len(apps),
            "session_count": sum(item["session_count"] for item in apps),
            "site_seconds": site_seconds,
            "site_label": format_clock(site_seconds),
            "site_count": len(visits),
            "host_count": len(hosts),
            "video_seconds": video_seconds,
            "video_label": format_clock(video_seconds),
            "video_count": video_count,
            "app_compact": compact_clock(app_seconds),
            "site_compact": compact_clock(site_seconds),
            "video_compact": compact_clock(video_seconds),
        },
        "app_intro": app_line,
        "narrative": narrative,
        "daily_summary": daily_summary,
        "current": current,
        "limits": limits,
        "next_rule": next_rule,
        "apps": apps,
        "sites": {"hosts": hosts, "visits": visits},
        "videos": video_groups,
        "hint": "Screen time is app foreground time only. Website and video minutes classify the same interval; they are not added to screen time.",
    }
