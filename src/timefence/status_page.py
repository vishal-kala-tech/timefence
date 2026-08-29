import html
from datetime import datetime
from pathlib import Path

from .browse import top_sites
from .budget import (
    format_clock,
    format_span,
    format_window_name,
    summarize,
)
from .config import load_config

DEFAULT_STATUS_PORT = 8743
STATUS_HTML_NAME = "status.html"
REFRESH_SECONDS = 15


def used_percent(used, limit):
    if not limit:
        return 0
    return min(100, int(round(100 * int(used or 0) / int(limit))))


def _limit_label(limit):
    if not limit:
        return "No cap"
    return format_clock(limit)


def _remaining_label(limit, remaining):
    if not limit:
        return "No cap"
    if remaining == 0:
        return "No time"
    return format_clock(remaining)


def _status_kind(row):
    if row.get("allowed"):
        return "ok"
    return "blocked"


def _status_short(row):
    text = row.get("now") or ""
    if row.get("allowed"):
        return "OK to use now"
    if "daily limit" in text:
        return "Daily time is used up"
    if "window" in text and "limit" in text:
        return "This window's time is used up"
    return "Not an allowed time right now"


def page_model(cfg, state_dir, now=None):
    now = now or datetime.now()
    resources = []
    for row in summarize(cfg, state_dir, now=now):
        windows = []
        for window in row.get("windows") or []:
            windows.append(
                {
                    **window,
                    "name": format_window_name(window.get("id")),
                    "span": format_span(window.get("start"), window.get("end")),
                    "used_label": format_clock(window.get("used")),
                    "limit_label": _limit_label(window.get("limit")),
                    "remaining_label": _remaining_label(
                        window.get("limit"), window.get("remaining")
                    ),
                    "percent": used_percent(window.get("used"), window.get("limit")),
                }
            )
        resources.append(
            {
                **row,
                "kind": _status_kind(row),
                "status_short": _status_short(row),
                "daily_used_label": format_clock(row.get("daily_used")),
                "daily_limit_label": _limit_label(row.get("daily_limit")),
                "daily_remaining_label": _remaining_label(
                    row.get("daily_limit"), row.get("daily_remaining")
                ),
                "percent": used_percent(row.get("daily_used"), row.get("daily_limit")),
                "windows": windows,
            }
        )
    sites = []
    if cfg.get("log_browsing", True):
        ranked = top_sites(state_dir, now=now, limit=10)
        top_seconds = ranked[0]["seconds"] if ranked else 0
        for item in ranked:
            sites.append(
                {
                    "host": item["host"],
                    "title": item.get("title") or "",
                    "seconds": item["seconds"],
                    "visits": item["visits"],
                    "used_label": format_clock(item["seconds"]),
                    "percent": used_percent(item["seconds"], top_seconds) if top_seconds else 0,
                }
            )
    stamp = now.strftime("%A, %B ") + f"{now.day}, {now.year}"
    clock = now.strftime("%I:%M %p").lstrip("0")
    return {
        "date_label": stamp,
        "clock": clock,
        "refresh_seconds": REFRESH_SECONDS,
        "show_sites": bool(cfg.get("log_browsing", True)),
        "sites": sites,
        "resources": resources,
    }


def _bar(percent, kind):
    pct = max(0, min(100, int(percent or 0)))
    return (
        f'<div class="bar" aria-hidden="true"><div class="fill {html.escape(kind)}" '
        f'style="width:{pct}%"></div></div>'
    )


def _window_html(window):
    current = " current" if window.get("current") else ""
    span = html.escape(window.get("span") or "All day")
    name = html.escape(window["name"])
    extra = " · happening now" if window.get("current") else ""
    if window.get("limit"):
        detail = (
            f'{html.escape(window["used_label"])} used · '
            f'{html.escape(window["remaining_label"])} left'
        )
    else:
        detail = f'{html.escape(window["used_label"])} used · no cap'
    return (
        f'<li class="window{current}">'
        f"<strong>{name}</strong> ({span}){extra}"
        f"<span>{detail}</span></li>"
    )


def _card_html(row):
    kind = row["kind"]
    windows = "".join(_window_html(w) for w in row.get("windows") or [])
    window_block = f'<ul class="windows">{windows}</ul>' if windows else ""
    remaining = html.escape(row["daily_remaining_label"])
    limit = html.escape(row["daily_limit_label"])
    used = html.escape(row["daily_used_label"])
    if row.get("daily_limit"):
        numbers = (
            f'<p class="remaining">{remaining} left today</p>'
            f'<p class="meta">{used} used of {limit}</p>'
        )
    else:
        numbers = (
            f'<p class="remaining">No daily cap</p>'
            f'<p class="meta">{used} used today</p>'
        )
    return f'''
<article class="card {html.escape(kind)}">
  <header>
    <h2>{html.escape(row["label"])}</h2>
    <p class="badge">{html.escape(row["status_short"])}</p>
  </header>
  {numbers}
  {_bar(row["percent"], kind)}
  {window_block}
</article>
'''


def _sites_html(model):
    if not model.get("show_sites"):
        return ""
    rows = []
    for item in model.get("sites") or []:
        host = html.escape(item["host"])
        used = html.escape(item["used_label"])
        rows.append(
            f'<li><div class="site-row"><strong>{host}</strong>'
            f"<span>{used}</span></div>"
            f'{_bar(item["percent"], "ok")}</li>'
        )
    body = (
        f'<ol class="sites">{"".join(rows)}</ol>'
        if rows
        else '<p class="empty">No websites yet today.</p>'
    )
    return f'''
<article class="card sites">
  <header>
    <h2>Top websites today</h2>
  </header>
  {body}
</article>
'''


def render_html(model):
    cards = "".join(_card_html(row) for row in model["resources"])
    if not cards:
        cards = '<p class="empty">Nothing is set up to track yet.</p>'
    refresh = int(model.get("refresh_seconds") or REFRESH_SECONDS)
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{refresh}">
  <title>Your time today</title>
  <style>
    :root {{
      --bg: #f4f1ea;
      --card: #fffdf8;
      --ink: #1c1917;
      --muted: #57534e;
      --line: #e7e5e4;
      --ok: #15803d;
      --ok-bg: #dcfce7;
      --blocked: #b45309;
      --blocked-bg: #ffedd5;
      --fill-ok: #22c55e;
      --fill-blocked: #f97316;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #1c1917;
        --card: #292524;
        --ink: #fafaf9;
        --muted: #a8a29e;
        --line: #44403c;
        --ok-bg: #14532d;
        --blocked-bg: #7c2d12;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }}
    main {{
      max-width: 720px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    h1 {{
      font-size: 2rem;
      margin: 0 0 6px;
    }}
    .when {{
      color: var(--muted);
      margin: 0 0 24px;
      font-size: 1.05rem;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 20px 22px 18px;
      margin-bottom: 16px;
    }}
    .card header {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      flex-wrap: wrap;
    }}
    h2 {{
      margin: 0;
      font-size: 1.45rem;
    }}
    .badge {{
      margin: 0;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 0.9rem;
    }}
    .ok .badge {{ background: var(--ok-bg); color: var(--ok); }}
    .blocked .badge {{ background: var(--blocked-bg); color: var(--blocked); }}
    .remaining {{
      font-size: 1.7rem;
      font-weight: 700;
      margin: 14px 0 4px;
    }}
    .meta {{
      margin: 0 0 12px;
      color: var(--muted);
    }}
    .bar {{
      height: 12px;
      background: var(--line);
      border-radius: 999px;
      overflow: hidden;
    }}
    .fill {{
      height: 100%;
      border-radius: 999px;
    }}
    .fill.ok {{ background: var(--fill-ok); }}
    .fill.blocked {{ background: var(--fill-blocked); }}
    .windows {{
      list-style: none;
      padding: 12px 0 0;
      margin: 0;
    }}
    .window {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      padding: 8px 0;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .window.current {{
      color: var(--ink);
      font-weight: 600;
    }}
    ol.sites {{
      list-style: decimal;
      padding: 12px 0 0 22px;
      margin: 0;
    }}
    ol.sites li {{
      padding: 10px 0 8px;
      border-top: 1px solid var(--line);
    }}
    ol.sites li:first-child {{
      border-top: 0;
      padding-top: 4px;
    }}
    .site-row {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }}
    .empty {{ color: var(--muted); }}
    footer {{
      margin-top: 20px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Your time today</h1>
    <p class="when">{html.escape(model["date_label"])} · {html.escape(model["clock"])}</p>
    {cards}
    {_sites_html(model)}
    <footer>This page updates every {refresh} seconds.</footer>
  </main>
</body>
</html>
'''


def render(app_dir, now=None, cfg=None):
    app_dir = Path(app_dir)
    now = now or datetime.now()
    cfg = cfg or load_config(app_dir / "config/rules.json")
    return render_html(page_model(cfg, app_dir / "state", now=now))


def write_html(app_dir, now=None, cfg=None):
    app_dir = Path(app_dir)
    path = app_dir / STATUS_HTML_NAME
    path.write_text(render(app_dir, now=now, cfg=cfg), encoding="utf-8")
    return path
