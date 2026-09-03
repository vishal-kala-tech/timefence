"""Kid-facing remaining-time HTML. No PIN; reads JSON usage + grants.

`write_html` also dumps `status.html` under the app dir so the page works if
the HTTP server is down. Live numbers still come from `render()` on each GET.
"""

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
        if row.get("bonus"):
            return "Bonus time"
        return "OK to use now"
    if "daily limit" in text:
        return "Daily time is used up"
    if "window" in text and "limit" in text:
        return "This window's time is used up"
    return "Not an allowed time right now"


def page_model(cfg, state_dir, now=None):
    """Numbers + labels for the HTML template. Percent bars are relative to that resource's cap."""
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
                "bonus": row.get("bonus"),
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


ICON_HOSTS = (
    ("youtube shorts", "youtube.com"),
    ("youtube", "youtube.com"),
    ("vs code", "code.visualstudio.com"),
    ("visual studio", "visualstudio.com"),
    ("chrome", "chrome.google.com"),
    ("safari", "apple.com"),
    ("roblox", "roblox.com"),
    ("cursor", "cursor.com"),
    ("pycharm", "jetbrains.com"),
    ("terminal", "apple.com"),
    ("github", "github.com"),
)


def _icon_host(name):
    raw = str(name or "").strip().lower().removeprefix("www.")
    if not raw:
        return None
    if "." in raw and " " not in raw and not raw.startswith("127.") and raw != "localhost":
        return raw.split("/")[0]
    for needle, host in ICON_HOSTS:
        if raw == needle or needle in raw:
            return host
    return None


def _mark_html(name):
    letter = html.escape((str(name or "?").removeprefix("www.")[:1] or "?").upper())
    host = _icon_host(name)
    if not host:
        return f'<div class="usage-mark" aria-hidden="true">{letter}</div>'
    src = html.escape("https://www.google.com/s2/favicons?domain=" + host + "&sz=64")
    return (
        f'<div class="usage-mark has-icon" aria-hidden="true">{letter}'
        f'<img src="{src}" alt="" referrerpolicy="no-referrer"></div>'
    )


def _compact_clock(seconds):
    seconds = max(0, int(seconds or 0))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    return f"{secs}s"


def _fill_kind(percent, kind, relative=False):
    if kind == "blocked":
        return "blocked"
    if not relative and int(percent or 0) >= 80:
        return "warn"
    return "ok"


def _bar(percent, kind):
    pct = max(0, min(100, int(percent or 0)))
    fill = _fill_kind(pct, kind)
    return (
        f'<div class="bar-track" aria-hidden="true"><div class="bar {html.escape(fill)}" '
        f'style="width:{pct}%"></div></div>'
    )


def _usage_bar(percent, kind, relative=False):
    pct = max(0, min(100, int(percent or 0)))
    fill = _fill_kind(pct, kind, relative=relative)
    return (
        f'<div class="bar-track usage-track" aria-hidden="true">'
        f'<div class="bar {html.escape(fill)}" style="width:{pct}%"></div></div>'
    )


def _window_html(window):
    current = " is-current" if window.get("current") else ""
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
        f'<div class="window-copy"><strong>{name}</strong>'
        f'<span class="window-span">{span}{extra}</span></div>'
        f'<span class="window-detail">{detail}</span></li>'
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
    bonus = ""
    if row.get("bonus"):
        bonus = f'<p class="bonus">{html.escape(row["bonus"])}</p>'
    label = html.escape(row["label"])
    return f'''
<article class="card {html.escape(kind)}">
  <div class="card-head">
    <div class="resource-heading">
      {_mark_html(row["label"])}
      <h2>{label}</h2>
    </div>
    <p class="badge">{html.escape(row["status_short"])}</p>
  </div>
  {numbers}
  {bonus}
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
        compact = html.escape(_compact_clock(item["seconds"]))
        rows.append(
            f'<li class="usage-row">'
            f'{_mark_html(item["host"])}'
            f'<div class="usage-copy"><div class="usage-name" title="{host} · {used}">{host}</div></div>'
            f'{_usage_bar(item["percent"], "ok", relative=True)}'
            f'<div class="usage-duration">{compact}</div>'
            f"</li>"
        )
    body = (
        f'<ol class="sites">{"".join(rows)}</ol>'
        if rows
        else '<p class="empty-note">No websites yet today.</p>'
    )
    return f'''
<article class="card sites">
  <div class="card-head"><h2>Top websites today</h2></div>
  {body}
</article>
'''


def render_html(model):
    cards = "".join(_card_html(row) for row in model["resources"])
    if not cards:
        cards = (
            '<article class="card">'
            '<p class="empty-note">Nothing is set up to track yet.</p>'
            "</article>"
        )
    refresh = int(model.get("refresh_seconds") or REFRESH_SECONDS)
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{refresh}">
  <title>Your time today</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400..700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --tf-bg: #F7F6F2;
      --tf-surface: #FFFFFF;
      --tf-text: #202020;
      --tf-text-secondary: #5F5D58;
      --tf-text-muted: #85827C;
      --tf-border: #E5E2DC;
      --tf-divider: #ECE9E4;
      --tf-primary: #2563EB;
      --tf-bar: #3F5C88;
      --tf-track: #E7E7E7;
      --tf-warning: #D99520;
      --tf-danger: #DC4C4C;
      --tf-success: #3D8B68;
      --tf-shadow: 0 1px 2px rgba(0, 0, 0, 0.02), 0 4px 14px rgba(0, 0, 0, 0.025);
      --tf-radius: 20px;
      --ok: var(--tf-success);
      --ok-bg: #e8f4ec;
      --warn: var(--tf-warning);
      --warn-bg: #fff4e5;
      --danger: var(--tf-danger);
      --danger-bg: #fde8e6;
    }}
    * {{ box-sizing: border-box; }}
    html {{ color-scheme: light; }}
    body {{
      margin: 0;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-weight: 400;
      background: var(--tf-bg);
      color: var(--tf-text);
    }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 0 20px 64px; }}
    .app-header {{
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      align-items: center;
      padding: 14px 0 12px;
      margin: 0 0 8px;
      background: var(--tf-bg);
    }}
    .brand {{
      font-size: 22px;
      font-weight: 700;
      letter-spacing: -0.03em;
      color: var(--tf-text);
    }}
    .page-intro {{ margin: 8px 0 18px; }}
    h1 {{
      margin: 0;
      font-size: 28px;
      font-weight: 650;
      letter-spacing: -0.03em;
    }}
    .page-lede {{
      margin: 6px 0 0;
      color: var(--tf-text-secondary);
      font-size: 15px;
    }}
    .lists-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 16px;
    }}
    .card {{
      background: var(--tf-surface);
      border: 1px solid var(--tf-border);
      border-radius: var(--tf-radius);
      padding: 24px;
      margin-bottom: 16px;
      box-shadow: var(--tf-shadow);
    }}
    .lists-grid > .card {{ margin-bottom: 0; }}
    .card-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }}
    .card-head h2, .resource-heading h2 {{
      margin: 0;
      font-size: 20px;
      font-weight: 650;
      letter-spacing: -0.02em;
      color: var(--tf-text);
    }}
    .resource-heading {{
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
    }}
    .usage-mark {{
      width: 32px;
      height: 32px;
      border-radius: 9px;
      display: grid;
      place-items: center;
      justify-self: start;
      font-size: 0.78rem;
      font-weight: 600;
      color: #fff;
      background: var(--tf-bar);
      overflow: hidden;
      position: relative;
      flex: 0 0 32px;
    }}
    .usage-mark.has-icon {{
      background: #fff;
      border: 1px solid var(--tf-border);
      color: var(--tf-text-muted);
      padding: 4px;
    }}
    .usage-mark img {{
      position: absolute;
      inset: 4px;
      width: calc(100% - 8px);
      height: calc(100% - 8px);
      object-fit: contain;
    }}
    .badge {{
      margin: 0;
      font-weight: 600;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 13px;
    }}
    .ok .badge {{ background: var(--ok-bg); color: var(--ok); }}
    .blocked .badge {{ background: var(--danger-bg); color: var(--danger); }}
    .remaining {{
      font-size: 36px;
      font-weight: 700;
      letter-spacing: -0.02em;
      line-height: 1.05;
      margin: 8px 0 6px;
      color: var(--tf-text);
    }}
    .meta {{
      margin: 0 0 14px;
      color: var(--tf-text-muted);
      font-size: 14px;
    }}
    .bonus {{
      margin: -6px 0 12px;
      font-weight: 550;
      font-size: 14px;
      color: var(--tf-primary);
    }}
    .bar-track {{
      height: 10px;
      background: var(--tf-track);
      border-radius: 99px;
      overflow: hidden;
      min-width: 48px;
    }}
    .bar {{
      height: 10px;
      background: var(--tf-bar);
      border-radius: 99px;
    }}
    .bar.warn {{ background: var(--tf-warning); }}
    .bar.blocked {{ background: var(--tf-danger); }}
    .windows {{
      list-style: none;
      padding: 8px 0 0;
      margin: 14px 0 0;
      border-top: 1px solid var(--tf-divider);
    }}
    .window {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      padding: 10px 0;
      border-top: 1px solid var(--tf-divider);
      color: var(--tf-text-muted);
      font-size: 14px;
    }}
    .window:first-child {{ border-top: 0; }}
    .window-copy {{ display: flex; flex-direction: column; gap: 2px; min-width: 0; }}
    .window strong {{ color: var(--tf-text); font-weight: 550; }}
    .window-span {{ font-size: 13px; }}
    .window-detail {{ font-size: 13px; }}
    .window.is-current {{ color: var(--tf-text); }}
    .window.is-current strong {{ color: var(--tf-primary); }}
    ol.sites {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}
    .usage-row {{
      display: grid;
      grid-template-columns: 40px minmax(96px, 1.1fr) minmax(64px, 1.35fr) 4.5rem;
      gap: 10px;
      align-items: center;
      padding: 10px 0;
    }}
    .usage-copy {{ min-width: 0; }}
    .usage-name {{
      font-size: 15px;
      font-weight: 550;
      color: #252525;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .usage-duration {{
      font-size: 13px;
      font-weight: 550;
      color: var(--tf-text-secondary);
      text-align: right;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }}
    .empty-note {{ color: var(--tf-text-muted); margin: 0; }}
    footer {{
      margin-top: 24px;
      color: var(--tf-text-muted);
      font-size: 13px;
    }}
    @media (max-width: 700px) {{
      main {{ padding: 0 14px 48px; }}
      .card {{ padding: 16px; }}
      .app-header {{ position: static; }}
      .lists-grid {{ grid-template-columns: 1fr; }}
      .remaining {{ font-size: 30px; }}
      .usage-row {{ grid-template-columns: 40px minmax(72px, 1.1fr) minmax(48px, 1.2fr) 3.75rem; }}
    }}
  </style>
</head>
<body>
  <main>
    <header class="app-header"><div class="brand">TimeFence</div></header>
    <div class="page-intro">
      <h1>Your time today</h1>
      <p class="page-lede when">{html.escape(model["date_label"])} · {html.escape(model["clock"])}</p>
    </div>
    <div class="lists-grid">
    {cards}
    </div>
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
