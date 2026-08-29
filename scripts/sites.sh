#!/bin/bash

# Print today's Chrome front-tab browse log in order.
# Usage: ./scripts/sites.sh [YYYY-MM-DD]

set -e

STATE="${TIMEFENCE_STATE:-$HOME/Library/Application Support/TimeFence/state}"
DAY="${1:-}"

python3 - "$STATE" "$DAY" <<'PY'
import json
import sys
from datetime import date
from pathlib import Path

state_dir = Path(sys.argv[1])
day = sys.argv[2] or date.today().isoformat()
path = state_dir / "browse" / f"{day}.json"


def minutes(seconds):
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"


if not path.exists():
    print(f"No browse log for {day}.")
    print(f"Expected: {path}")
    raise SystemExit(0)

try:
    payload = json.loads(path.read_text())
except (OSError, ValueError):
    print(f"unreadable ({path})")
    raise SystemExit(1)

visits = payload.get("visits") or []
if not visits:
    print(f"No sites recorded for {day}.")
    raise SystemExit(0)

print(f"browse ({len(visits)} in order on {day}):")
for index, item in enumerate(visits, start=1):
    start = item.get("first_seen") or "?"
    end = item.get("last_seen") or "?"
    host = item.get("host") or "?"
    title = item.get("title") or "(no title)"
    url = item.get("url") or ""
    print(f"  {index:>3}. {start}-{end}  {minutes(item.get('usage_seconds')):>8}  {host}  {title}  {url}")
print(f"Excel: {path.with_suffix('.txt')}")
PY
