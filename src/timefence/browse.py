"""Front-tab history for whichever configured browser is in front. Not a budget.

`log_browsing` records the active tab while Chrome or Safari (or another
adapter) is frontmost. YouTube usage still goes through `resources/youtube.py`.
Local hosts (status page, parent setup) are dropped from top-sites ranking.

Visit rows are stored in `state/screen_time.sqlite` (`browse_visits`). JSON
under `state/browse/` is a cache; leftover JSON is used until SQLite has rows
for that day.
"""

import json
import logging
import subprocess
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .usage import _cell, _day, _sqlite_store, _timestamp
from .browsers.macos.chrome import browse_script as chrome_browse_script

MAX_VISITS = 5000
TOP_SITES = 10
BROWSE_RESOURCE = "browse"
BROWSE_TABLE_FIELDS = (
    "date",
    "host",
    "url",
    "title",
    "first_seen",
    "last_seen",
    "seconds",
)
INSPECT_SCRIPT = chrome_browse_script()


def _clean_title(title):
    text = (title or "").strip()
    if text in ("missing value",):
        return ""
    return text


def parse_page(url, title=""):
    url = (url or "").strip()
    if url in ("", "missing value", "NO", "YES"):
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.netloc or "").lower()
    if not host:
        return None
    canonical = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )
    return {
        "host": host,
        "url": canonical,
        "title": _clean_title(title),
    }


def inspect(cfg=None):
    """Active tab of the first configured browser that is frontmost. None otherwise."""
    from .browsers import read_frontmost_tab

    tab = read_frontmost_tab(cfg=cfg, run=subprocess.run)
    if tab is None:
        return None
    page = parse_page(tab.url, tab.title)
    if page is not None and tab.browser:
        page["browser"] = tab.browser
    return page


def browse_path(state_dir, now=None):
    return Path(state_dir) / BROWSE_RESOURCE / f"{_day(now).isoformat()}.json"


def browse_table_path(state_dir, now=None):
    return Path(state_dir) / BROWSE_RESOURCE / f"{_day(now).isoformat()}.txt"


def _visit_entry(payload):
    if not isinstance(payload, dict):
        return None
    url = str(payload.get("url") or "").strip()
    host = str(payload.get("host") or "").strip()
    if not url or not host:
        return None
    entry = {
        "host": host,
        "url": url,
        "title": str(payload.get("title") or ""),
        "first_seen": str(payload.get("first_seen") or ""),
        "last_seen": str(payload.get("last_seen") or ""),
        "usage_seconds": int(payload.get("usage_seconds") or 0),
    }
    browser = str(payload.get("browser") or "").strip()
    if browser:
        entry["browser"] = browser
    return entry


def empty_browse_state(now=None):
    return {"date": _day(now).isoformat(), "visits": []}


def _load_browse_json(state_dir, now=None):
    path = browse_path(state_dir, now=now)
    if not path.exists():
        return empty_browse_state(now)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError, TypeError) as exc:
        logging.warning("Corrupt browse state (%s); resetting", exc)
        return empty_browse_state(now)
    visits = []
    for item in data.get("visits") or []:
        entry = _visit_entry(item)
        if entry:
            visits.append(entry)
    return {"date": data.get("date") or _day(now).isoformat(), "visits": visits}


def _overlay_browse_visits(state, state_dir, now=None):
    """Prefer SQLite visits. Copy leftover JSON into SQLite when that day has no rows yet."""
    store = _sqlite_store(state_dir)
    usage_date = _day(now).isoformat()
    visits = store.get_browse_visits(usage_date)
    if not visits:
        store.seed_browse_visits(usage_date, state.get("visits") or [])
        visits = store.get_browse_visits(usage_date)
    if visits:
        state["visits"] = visits
    return state


def load_browse_state(state_dir, now=None):
    return _overlay_browse_visits(_load_browse_json(state_dir, now=now), state_dir, now=now)


def display_host(host):
    text = str(host or "").strip().lower()
    if text.startswith("www."):
        text = text[4:]
    return text


def _is_local_host(host):
    """Status/parent pages on 127.0.0.1 would otherwise dominate top sites."""
    text = display_host(host)
    if text in ("localhost", "127.0.0.1", "::1"):
        return True
    return text.startswith("127.0.0.1:") or text.startswith("localhost:")


def top_sites(state_dir, now=None, limit=TOP_SITES):
    """Hosts ranked by time on the frontmost browser tab today."""
    limit = max(0, int(limit))
    buckets = {}
    for visit in load_browse_state(state_dir, now=now).get("visits") or []:
        host = display_host(visit.get("host"))
        if not host or _is_local_host(host):
            continue
        bucket = buckets.setdefault(
            host, {"host": host, "seconds": 0, "visits": 0, "title": ""}
        )
        bucket["seconds"] += int(visit.get("usage_seconds") or 0)
        bucket["visits"] += 1
        title = str(visit.get("title") or "").strip()
        if title:
            bucket["title"] = title
    ranked = sorted(
        buckets.values(),
        key=lambda item: (-item["seconds"], -item["visits"], item["host"]),
    )
    return ranked[:limit]


def write_browse_table(state_dir, now=None):
    day = _day(now).isoformat()
    state = load_browse_state(state_dir, now=now)
    rows = ["|".join(BROWSE_TABLE_FIELDS)]
    for visit in state.get("visits") or []:
        rows.append(
            "|".join(
                _cell(part)
                for part in (
                    day,
                    visit.get("host") or "",
                    visit.get("url") or "",
                    visit.get("title") or "",
                    visit.get("first_seen") or "",
                    visit.get("last_seen") or "",
                    int(visit.get("usage_seconds") or 0),
                )
            )
        )
    path = browse_table_path(state_dir, now=day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(rows) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _save_browse_state(path, state, state_dir):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)
    try:
        write_browse_table(state_dir, now=state.get("date"))
    except Exception:
        logging.exception("Browse table export failed")


def note_visit(state_dir, page, seconds, now=None):
    """Append or extend today's visit row. Same URL as last poll stays one session."""
    if not isinstance(page, dict):
        return None
    url = str(page.get("url") or "").strip()
    host = str(page.get("host") or "").strip()
    if not url or not host:
        return None
    usage_date = _day(now).isoformat()
    ts = _timestamp(now)
    title = str(page.get("title") or "")
    browser = str(page.get("browser") or "")
    store = _sqlite_store(state_dir)
    json_state = _load_browse_json(state_dir, now=now)
    store.seed_browse_visits(usage_date, json_state.get("visits") or [])
    result = store.add_browse_visit(
        usage_date,
        host,
        url,
        title,
        int(seconds),
        ts,
        browser=browser,
        max_rows=MAX_VISITS,
    )
    if result == "full":
        logging.warning("Browse history full (%s); not adding %s", MAX_VISITS, url)
    elif result == "inserted":
        logging.info("Visited %s %s", host, title or url)
    state = {"date": usage_date, "visits": store.get_browse_visits(usage_date)}
    _save_browse_state(browse_path(state_dir, now=now), state, state_dir)
    return state
