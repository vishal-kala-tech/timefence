#!/bin/bash

# Report whether timefence.main is loaded and running.
# Usage: ./scripts/status.sh [--watch] [--interval SECONDS]

APP="$HOME/Library/Application Support/TimeFence"
LOG="$HOME/Library/Logs/TimeFence"
PL="$HOME/Library/LaunchAgents/com.user.timefence.plist"
ERR_LOG="$LOG/timefence.err.log"
OUT_LOG="$LOG/timefence.out.log"
LABEL="com.user.timefence"
DOMAIN="gui/$(id -u)/$LABEL"

WATCH=0
INTERVAL=5

while [ $# -gt 0 ]; do
    case "$1" in
        -w|--watch) WATCH=1 ;;
        --interval)
            shift
            INTERVAL="${1:-5}"
            ;;
        -h|--help)
            echo "Usage: $0 [--watch] [--interval SECONDS]"
            echo "  Check LaunchAgent $LABEL and the timefence.main process."
            echo "  --watch     poll until interrupted"
            echo "  --interval  seconds between polls (default: 5)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: $0 [--watch] [--interval SECONDS]" >&2
            exit 2
            ;;
    esac
    shift
done

field() {
    # Read a launchctl print key: "state = running"
    printf '%s\n' "$1" | awk -F ' = ' -v key="$2" '
        $1 ~ "^[[:space:]]*" key "[[:space:]]*$" { sub(/^[[:space:]]+/, "", $2); print $2; exit }
    '
}

print_log_tail() {
    local path="$1"
    local name="$2"
    if [ ! -f "$path" ]; then
        echo "  $name: missing ($path)"
        return
    fi
    if [ ! -s "$path" ]; then
        echo "  $name: empty ($path)"
        return
    fi
    echo "  $name (last 5 lines of $path):"
    tail -n 5 "$path" | sed 's/^/    /'
}

check() {
    local healthy=0
    local svc=""
    local state="not loaded"
    local agent_pid=""
    local last_exit=""
    local runs=""
    local proc_pid=""
    local proc_line=""

    echo "==== $(date) ===="
    echo "TimeFence status"
    echo "  launch agent:    $PL"
    echo "  domain:          $DOMAIN"
    echo "  app:             $APP"
    echo "  stderr log:      $ERR_LOG"
    echo "  stdout log:      $OUT_LOG"

    if [ -f "$PL" ]; then
        echo "Plist: present"
    else
        echo "Plist: missing (not installed)"
    fi

    if svc="$(launchctl print "$DOMAIN" 2>/dev/null)"; then
        state="$(field "$svc" "state")"
        agent_pid="$(field "$svc" "pid")"
        last_exit="$(field "$svc" "last exit code")"
        runs="$(field "$svc" "runs")"
        echo "LaunchAgent: loaded"
        echo "  state:           ${state:-unknown}"
        echo "  pid:             ${agent_pid:-none}"
        echo "  runs:            ${runs:-unknown}"
        echo "  last exit code:  ${last_exit:-unknown}"
    else
        echo "LaunchAgent: not loaded"
        echo "  start with:      ./scripts/install.sh"
    fi

    proc_pid="$(pgrep -f '[Pp]ython.*timefence.main' | head -n 1 || true)"
    if [ -n "$proc_pid" ]; then
        proc_line="$(ps -o pid=,etime=,stat=,command= -p "$proc_pid" | sed 's/^ *//')"
        echo "Process: running"
        echo "  $proc_line"
        if [ -n "$agent_pid" ] && [ "$proc_pid" != "$agent_pid" ]; then
            echo "  warning: LaunchAgent pid $agent_pid does not match process pid $proc_pid"
        fi
    else
        echo "Process: not running"
        echo "  no Python -m timefence.main process"
    fi

    print_log_tail "$ERR_LOG" "stderr"
    print_log_tail "$OUT_LOG" "stdout"

    if [ "$state" = "running" ] && [ -n "$proc_pid" ]; then
        echo "Status: RUNNING"
        healthy=0
    else
        echo "Status: NOT RUNNING"
        healthy=1
    fi

    return "$healthy"
}

if [ "$WATCH" -eq 1 ]; then
    echo "Watching TimeFence every ${INTERVAL}s (Ctrl-C to stop)"
    while true; do
        check || true
        echo
        sleep "$INTERVAL"
    done
else
    check
fi
