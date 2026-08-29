#!/bin/bash

# English summary of videos watched and websites visited.
# Usage: ./scripts/activity.sh [YYYY-MM-DD]

set -e

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="${TIME_FENCE_HOME:-$HOME/Library/Application Support/TimeFence}"

if [ -d "$SRC/src/timefence" ]; then
    export PYTHONPATH="$SRC/src"
else
    export PYTHONPATH="${PYTHONPATH:-$APP/src}"
fi

export TIME_FENCE_HOME="$APP"

python3 - "$APP" "${1:-}" <<'PY'
import sys
from datetime import datetime
from pathlib import Path

from timefence.history import render

app = Path(sys.argv[1])
day = sys.argv[2].strip() if len(sys.argv) > 2 else ""
if day:
    now = datetime.strptime(day, "%Y-%m-%d").replace(hour=12, minute=0, second=0)
else:
    now = datetime.now()
sys.stdout.write(render(app, now=now))
PY
