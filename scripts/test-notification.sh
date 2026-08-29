#!/bin/bash

# Show a test TimeFence dialog without waiting for usage limits.
# Uses this repo's Python package when run from the project, so you do not
# need to reinstall just to try a notification change.

set -e

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Library/Application Support/TimeFence"

if [ -d "$SRC/src/timefence" ]; then
    export PYTHONPATH="$SRC/src"
    echo "Using project code: $SRC/src"
else
    export PYTHONPATH="${PYTHONPATH:-$APP/src}"
    echo "Using installed code: $PYTHONPATH"
fi

export TIME_FENCE_HOME="${TIME_FENCE_HOME:-$APP}"

python3 - "$1" <<'PY'
import logging
import sys
import timefence.notifications as n

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
print("module:", n.__file__)
if sys.argv[1] == "--countdown":
    print("Showing 6-second block countdown, then exiting.")
    ok = n.show_block_countdown("TimeFence", "YouTube has no time remaining today.")
else:
    print("Showing 6-second warning countdown in the background.")
    ok = n.show_notification("TimeFence", "Test notification from TimeFence.")
print("sent" if ok else "failed")
raise SystemExit(0 if ok else 1)
PY
