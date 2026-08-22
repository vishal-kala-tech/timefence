#!/bin/bash

CONTROLLER_HOME="$HOME/Developer/roblox-controller"
STATE_DIR="$CONTROLLER_HOME/state"
LOG_DIR="$CONTROLLER_HOME/logs"

mkdir -p "$STATE_DIR" "$LOG_DIR"

NOW=$(date +%s)
CURRENT_HOUR=$(date '+%Y-%m-%d-%H')
TODAY=$(date '+%Y-%m-%d')
LOG_FILE="$LOG_DIR/roblox_controller_$TODAY.log"

STATE_FILE="$STATE_DIR/$CURRENT_HOUR.state"

MAX_USAGE=300  # 5 minutes per hour

log() {
    printf "%s | %s\n" \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$1" >> "$LOG_FILE"
}

# Initialize state
if [ ! -f "$STATE_FILE" ]; then
cat > "$STATE_FILE" <<EOF
usage=0
last_check=$NOW
EOF
    log "NEW_HOUR | state initialized"
fi

source "$STATE_FILE"

ELAPSED=$((NOW - last_check))

log "STATUS | usage=${usage}s | elapsed=${ELAPSED}s"

# prevent sleep/wake spikes
if (( ELAPSED > 60 )); then
    ELAPSED=15
fi

# Detect Roblox process (covers multiple possible names)
ROBLOX_PIDS=$(pgrep -f "Roblox" 2>/dev/null)

if [ -n "$ROBLOX_PIDS" ]; then

    usage=$((usage + ELAPSED))

    log "ROBLOX_DETECTED | USAGE_UPDATE | +${ELAPSED}s | total=${usage}s"

    if (( usage >= MAX_USAGE )); then

        log "LIMIT_REACHED | killing Roblox (usage=${usage}s)"

        for pid in $ROBLOX_PIDS; do
            kill -9 "$pid" 2>/dev/null
            log "KILLED_PID | $pid"
        done

        usage=$MAX_USAGE
    fi
fi

# Save state
cat > "$STATE_FILE" <<EOF
usage=$usage
last_check=$NOW
EOF