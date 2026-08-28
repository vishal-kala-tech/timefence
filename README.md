# TimeFence

macOS parental-control prototype with a Python controller and JSON configuration designed for eventual remote/API updates.

## Policy model
Each resource has separate `weekday` and `weekend` policies, a daily usage limit, and any number of allowed windows. Daily usage is shared across all windows. A `daily_limit_minutes` value of `0` means no usage cap; the schedule still applies.

## Config
Edit `config/rules.json`. The controller reloads it every cycle, so an eventual API/sync agent can atomically replace this file after validating a downloaded config. `revision` makes remote changes easy to identify.

## Install
`./scripts/install.sh`

Runtime files are installed under `~/Library/Application Support/TimeFence`, logs under `~/Library/Logs/TimeFence`, and the LaunchAgent under `~/Library/LaunchAgents`.

## Current resources
- Roblox: process detection and termination.
- YouTube: Google Chrome active-tab detection and tab closing via AppleScript.

## Future API flow
Remote API -> download candidate JSON -> validate -> write temporary file -> atomic rename to `rules.json` -> controller reloads next cycle.
