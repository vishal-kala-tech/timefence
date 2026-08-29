#!/bin/bash

# Print today's YouTube / Shorts watch history in order.
# Usage: ./scripts/watched.sh [YYYY-MM-DD]

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


def minutes(seconds):
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"


found = False
for name in ("youtube", "youtube_shorts"):
    path = state_dir / name / f"{day}.json"
    if not path.exists():
        continue
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError):
        print(f"{name}: unreadable ({path})")
        continue
    videos = payload.get("videos") or []
    if not videos:
        continue
    found = True
    print(f"{name} ({len(videos)} in order on {day}):")
    for index, item in enumerate(videos, start=1):
        start = item.get("first_seen") or "?"
        end = item.get("last_seen") or "?"
        title = item.get("title") or "(no title)"
        channel = item.get("channel") or "(no channel)"
        url = item.get("url") or item.get("id") or ""
        print(f"  {index:>3}. {start}-{end}  {minutes(item.get('usage_seconds')):>8}  {channel}  {title}  {url}")

if not found:
    print(f"No watched videos recorded for {day}.")
    print(f"State dir: {state_dir}")
PY
