#!/bin/bash

# Open the parent TimeFence setup page (rules + grant) in the default browser.
# Usage: ./scripts/setup.sh

set -e

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="${TIME_FENCE_HOME:-$HOME/Library/Application Support/TimeFence}"
RULES="$APP/config/rules.json"

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

URL="http://127.0.0.1:${PORT}/setup"
echo "Parent setup page: $URL"
echo "The kid status page stays at http://127.0.0.1:${PORT}/"
open "$URL"
