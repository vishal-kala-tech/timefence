#!/bin/bash

CONTROLLER_HOME="$HOME/Developer"
STATE_DIR="$CONTROLLER_HOME/youtube-controller/state"
LOG_DIR="$CONTROLLER_HOME/youtube-controller/logs"

mkdir -p "$STATE_DIR" "$LOG_DIR"

NOW=$(date +%s)
CURRENT_HOUR=$(date '+%Y-%m-%d-%H')
TODAY=$(date '+%Y-%m-%d')
LOG_FILE="$LOG_DIR/youtube_controller_$TODAY.log"

STATE_FILE="$STATE_DIR/$CURRENT_HOUR.state"

MAX_USAGE_SECONDS=300

log() {
    printf "%s | %s\n" \
        "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$1" >> "$LOG_FILE"
}

#
# Initialize hourly state
#
if [ ! -f "$STATE_FILE" ]; then
cat > "$STATE_FILE" <<EOF
usage=0
last_check=$NOW
EOF

    log "NEW_HOUR | usage reset"
fi

source "$STATE_FILE"

ELAPSED=$((NOW - last_check))

log "STATUS | usage=${usage}s | elapsed=${ELAPSED}s"

#
# Cap elapsed time to avoid large jumps after sleep/wake.
#
if (( ELAPSED > 60 )); then
    ELAPSED=15
fi

#
# Close inactive/background YouTube tabs.
# Returns titles of closed tabs.
#
close_inactive_youtube_tabs() {
osascript <<'APPLESCRIPT'
tell application "Google Chrome"

    set outputText to ""

    repeat with w in windows

        try
            set activeTabIndex to active tab index of w
        on error
            set activeTabIndex to 1
        end try

        set tabsToClose to {}

        repeat with i from 1 to (count of tabs of w)

            set t to tab i of w
            set theURL to URL of t

            if theURL contains "youtube.com/" or theURL contains "youtu.be/" then

                if i is not activeTabIndex then

                    try
                        set tabTitle to title of t
                    on error
                        set tabTitle to "Unknown Title"
                    end try

                    set outputText to outputText & tabTitle & linefeed
                    set end of tabsToClose to t

                end if

            end if

        end repeat

        repeat with t in tabsToClose
            close t
        end repeat

    end repeat

    return outputText

end tell
APPLESCRIPT
}

#
# Close all YouTube tabs.
# Returns titles of closed tabs.
#
close_all_youtube_tabs() {
osascript <<'APPLESCRIPT'
tell application "Google Chrome"

    set outputText to ""

    repeat with w in windows

        set tabsToClose to {}

        repeat with t in tabs of w

            set theURL to URL of t

            if theURL contains "youtube.com/" or theURL contains "youtu.be/" then

                try
                    set tabTitle to title of t
                on error
                    set tabTitle to "Unknown Title"
                end try

                set outputText to outputText & tabTitle & linefeed

                set end of tabsToClose to t

            end if

        end repeat

        repeat with t in tabsToClose
            close t
        end repeat

    end repeat

    return outputText

end tell
APPLESCRIPT
}

#
# Close inactive YouTube tabs immediately.
#
CLOSED_TABS=$(close_inactive_youtube_tabs)

if [ -n "$CLOSED_TABS" ]; then
    while IFS= read -r title; do
        [ -n "$title" ] && log "CLOSED_INACTIVE_TAB | $title"
    done <<< "$CLOSED_TABS"
fi

#
# Determine if active tab is YouTube AND Chrome is frontmost.
#
ACTIVE_YOUTUBE=$(osascript <<'APPLESCRIPT'
tell application "System Events"

    set chromeFrontmost to false

    if exists process "Google Chrome" then
        set chromeFrontmost to frontmost of process "Google Chrome"
    end if

end tell

if chromeFrontmost then

    tell application "Google Chrome"

        if (count of windows) > 0 then

            set theURL to URL of active tab of front window

            if theURL contains "youtube.com/" or theURL contains "youtu.be/" then
                return "YES"
            end if

        end if

    end tell

end if

return "NO"
APPLESCRIPT
)

#
# Only count active YouTube usage.
#
if [ "$ACTIVE_YOUTUBE" = "YES" ]; then

    NEW_USAGE=$((usage + ELAPSED))

    log "ACTIVE_USAGE | +${ELAPSED}s | total=${NEW_USAGE}s"

    if (( NEW_USAGE >= MAX_USAGE_SECONDS )); then

        NEW_USAGE=$MAX_USAGE_SECONDS
        usage=$NEW_USAGE

        log "LIMIT_REACHED | total=${usage}s"

        CLOSED=$(close_all_youtube_tabs)

        if [ -n "$CLOSED" ]; then
            while IFS= read -r title; do
                [ -n "$title" ] && \
                    log "CLOSED_LIMIT_REACHED | $title"
            done <<< "$CLOSED"
        fi

    else

        usage=$NEW_USAGE

    fi

fi

#
# Persist state.
#
cat > "$STATE_FILE" <<EOF
usage=$usage
last_check=$NOW
EOF