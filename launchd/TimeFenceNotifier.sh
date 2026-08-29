#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$(tr -d '\r\n' < "$HERE/../Resources/python.path")"
exec "$PY" "$HERE/../Resources/TimeFenceNotifier.py" "$@"
