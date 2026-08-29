# Shared Python 3.10+ discovery for install.sh and bootstrap.sh.
# shellcheck shell=bash

timefence_python_ok() {
    local bin="$1"
    [ -n "$bin" ] && [ -x "$bin" ] || return 1
    "$bin" -c 'import sys, json, urllib.request; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}

timefence_find_python() {
    local path=""
    local candidate=""

    if path="$(command -v python3 2>/dev/null || true)"; then
        if [ "$path" = "/usr/bin/python3" ] && ! xcode-select -p >/dev/null 2>&1; then
            path=""
        fi
        if timefence_python_ok "$path"; then
            printf '%s\n' "$path"
            return 0
        fi
    fi

    for candidate in \
        /usr/local/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
        /opt/homebrew/bin/python3 \
        /opt/homebrew/opt/python@3.13/bin/python3 \
        /opt/homebrew/opt/python@3.12/bin/python3
    do
        if timefence_python_ok "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}
