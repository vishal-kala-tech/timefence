#!/bin/bash

# Give a resource extra time for the current session (until now+N or midnight).
# Usage:
#   ./scripts/grant.sh youtube 15
#   ./scripts/grant.sh roblox 10
#   ./scripts/grant.sh --list
#   ./scripts/grant.sh youtube --clear

set -e

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="${TIME_FENCE_HOME:-$HOME/Library/Application Support/TimeFence}"

if [ -d "$SRC/src/timefence" ]; then
    export PYTHONPATH="$SRC/src"
else
    export PYTHONPATH="${PYTHONPATH:-$APP/src}"
fi

export TIME_FENCE_HOME="$APP"

python3 - "$APP" "$@" <<'PY'
import sys
from pathlib import Path

from timefence.config import load_config
from timefence.grants import (
    clear_grant,
    find_resource,
    grant_from_config,
    grant_summary,
    list_grants,
)

app = Path(sys.argv[1])
args = sys.argv[2:]
rules = app / "config/rules.json"
state = app / "state"
try:
    cfg = load_config(rules)
except FileNotFoundError:
    print(f"No TimeFence config at {rules}")
    print("Install with: ./scripts/install.sh")
    raise SystemExit(1)

if not args or args[0] in ("-h", "--help"):
    print("Usage: ./scripts/grant.sh RESOURCE MINUTES")
    print("       ./scripts/grant.sh --list")
    print("       ./scripts/grant.sh RESOURCE --clear")
    raise SystemExit(0)

if args[0] in ("-l", "--list"):
    lines = list_grants(cfg, state)
    if not lines:
        print("No active bonus time.")
    else:
        print("Active bonus time:")
        for line in lines:
            print(f"  {line}")
    raise SystemExit(0)

if len(args) == 2 and args[1] in ("--clear", "clear", "0"):
    name, resource = find_resource(cfg, args[0])
    if name is None:
        print(f"Unknown resource {args[0]!r}")
        raise SystemExit(1)
    clear_grant(state, name)
    label = (resource or {}).get("display_name") or name
    print(f"Cleared bonus time for {label}.")
    raise SystemExit(0)

if len(args) != 2:
    print("Usage: ./scripts/grant.sh RESOURCE MINUTES")
    raise SystemExit(2)

try:
    minutes = int(args[1])
except ValueError:
    print("Minutes must be a whole number.")
    raise SystemExit(2)

try:
    name, grant = grant_from_config(cfg, state, args[0], minutes)
except ValueError as exc:
    print(exc)
    raise SystemExit(1)

resource = cfg["resources"][name]
label = resource.get("display_name") or name
print(f"{label}: {grant_summary(grant)}")
print("The kid page will show this after the next refresh.")
PY
