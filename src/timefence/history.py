from datetime import datetime
from pathlib import Path

from .browse import load_browse_state
from .budget import format_clock, format_time_of_day
from .config import load_config
from .policy import resource_label
from .usage import load_state

VIDEO_RESOURCES = ("youtube", "youtube_shorts")
DEFAULT_LABELS = {
    "youtube": "YouTube",
    "youtube_shorts": "YouTube Shorts",
}


def format_seen(value):
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) < 2:
        return None
    try:
        hhmm = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    except ValueError:
        return None
    return format_time_of_day(hhmm)


def _quoted(title):
    text = " ".join(str(title or "").split())
    if not text:
        return ""
    return '"' + text.replace('"', "'") + '"'


def _when(first_seen, last_seen):
    start = format_seen(first_seen)
    end = format_seen(last_seen)
    if start and end and start != end:
        return f"From {start} to {end}"
    if start:
        return f"At {start}"
    return "During the day"


def _count_clause(count, singular, plural):
    if count == 1:
        return f"1 {singular} was"
    return f"{count} {plural} were"


def _header(now):
    stamp = now.strftime("%A, %B ") + f"{now.day}, {now.year}"
    return f"Here is what was watched and visited on {stamp}."


def _video_sentence(item):
    when = _when(item.get("first_seen"), item.get("last_seen"))
    duration = format_clock(item.get("usage_seconds"))
    title = _quoted(item.get("title"))
    channel = " ".join(str(item.get("channel") or "").split())
    if title and channel:
        what = f"{title} by {channel}"
    elif title:
        what = title
    else:
        what = "a video"
    return f"{when}, {what} was watched for {duration}."


def _visit_sentence(item):
    when = _when(item.get("first_seen"), item.get("last_seen"))
    duration = format_clock(item.get("usage_seconds"))
    host = str(item.get("host") or "").lower()
    if host.startswith("www."):
        host = host[4:]
    host = host or "a website"
    title = _quoted(item.get("title"))
    if title:
        return f"{when}, {host} ({title}) was visited for {duration}."
    return f"{when}, {host} was visited for {duration}."


def _section_intro(label, count, total, singular, plural, verb):
    clause = _count_clause(count, singular, plural)
    return f"{label}: {clause} {verb}, for a total of {format_clock(total)}."


def _label_for(name, cfg):
    resource = (cfg.get("resources") or {}).get(name) or {}
    if resource.get("display_name"):
        return resource_label(name, resource)
    return DEFAULT_LABELS.get(name, name)


def summarize(cfg, state_dir, now=None):
    now = now or datetime.now()
    cfg = cfg or {}
    sections = []
    for name in VIDEO_RESOURCES:
        videos = load_state(state_dir, name, now=now).get("videos") or []
        sections.append(
            {
                "kind": "videos",
                "name": name,
                "label": _label_for(name, cfg),
                "items": videos,
                "total": sum(int(item.get("usage_seconds") or 0) for item in videos),
            }
        )
    visits = load_browse_state(state_dir, now=now).get("visits") or []
    sections.append(
        {
            "kind": "visits",
            "name": "browse",
            "label": "Websites",
            "items": visits,
            "total": sum(int(item.get("usage_seconds") or 0) for item in visits),
        }
    )
    return sections


def format_summary(sections, now=None):
    now = now or datetime.now()
    nonempty = [section for section in sections if section.get("items")]
    if not nonempty:
        return _header(now) + "\nNo videos or websites were recorded.\n"
    lines = [_header(now), ""]
    for section in nonempty:
        items = section["items"]
        if section["kind"] == "videos":
            lines.append(
                _section_intro(
                    section["label"],
                    len(items),
                    section["total"],
                    "video",
                    "videos",
                    "watched",
                )
            )
            lines.extend(_video_sentence(item) for item in items)
        else:
            lines.append(
                _section_intro(
                    section["label"],
                    len(items),
                    section["total"],
                    "page",
                    "pages",
                    "visited",
                )
            )
            lines.extend(_visit_sentence(item) for item in items)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render(app_dir, now=None):
    now = now or datetime.now()
    app_dir = Path(app_dir)
    cfg_path = app_dir / "config/rules.json"
    cfg = load_config(cfg_path) if cfg_path.exists() else {}
    return format_summary(summarize(cfg, app_dir / "state", now=now), now=now)
