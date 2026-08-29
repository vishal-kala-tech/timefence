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

python3 - <<'PY'
import timefence.notifications as n
print("module:", n.__file__)
ok = n.show_notification("TimeFence", "Test notification from TimeFence.")
print("sent" if ok else "failed")
raise SystemExit(0 if ok else 1)
PY
