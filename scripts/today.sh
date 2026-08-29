#!/bin/bash

# Open the kid's TimeFence usage page in the default browser.
# Usage: ./scripts/today.sh

set -e

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="${TIME_FENCE_HOME:-$HOME/Library/Application Support/TimeFence}"
RULES="$APP/config/rules.json"
PAGE="$APP/status.html"

PORT=8743
if [ -f "$RULES" ]; then
    PARSED="$(python3 -c "
import json
from pathlib import Path
p = Path('$RULES')
try:
    cfg = json.loads(p.read_text())
    print(int(cfg.get('status_port', 8743)))
except Exception:
    print(8743)
" 2>/dev/null || echo 8743)"
    PORT="$PARSED"
fi

URL="http://127.0.0.1:${PORT}/"
echo "Kid status page: $URL"
if [ -f "$PAGE" ]; then
    echo "Also saved at: $PAGE"
fi
open "$URL"
