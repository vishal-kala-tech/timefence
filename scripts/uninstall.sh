#!/bin/bash

# Path to the TimeFence LaunchAgent.
PL="$HOME/Library/LaunchAgents/com.user.timefence.plist"

# Stop and unload the TimeFence LaunchAgent if it is running.
launchctl bootout gui/$(id -u) "$PL" 2>/dev/null || true

# Remove the LaunchAgent plist.
rm -f "$PL"

# Remove the TimeFence application, configuration, and state files.
rm -rf "$HOME/Library/Application Support/TimeFence"

# Logs under ~/Library/Logs/TimeFence are intentionally retained.
echo "Removed TimeFence (logs retained)"