#!/bin/bash

# Show allowed vs remaining budget for each enabled resource.
# Uses live config and today's usage under Application Support.
# Usage: ./scripts/budget.sh

set -e

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="${TIME_FENCE_HOME:-$HOME/Library/Application Support/TimeFence}"

if [ -d "$SRC/src/timefence" ]; then
    export PYTHONPATH="$SRC/src"
else
    export PYTHONPATH="${PYTHONPATH:-$APP/src}"
fi

export TIME_FENCE_HOME="$APP"

python3 - "$APP" <<'PY'
import sys
from pathlib import Path

from timefence.budget import render

app = Path(sys.argv[1])
try:
    sys.stdout.write(render(app))
except FileNotFoundError:
    print(f"No TimeFence config at {app / 'config/rules.json'}")
    print("Install with: ./scripts/install.sh")
    raise SystemExit(1)
PY
