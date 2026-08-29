# TimeFence

macOS parental-control prototype with a Python controller and JSON configuration designed for eventual remote/API updates.

## Policy model
JSON is the source of truth. Resource modules only detect activity and enforce blocks. The controller resolves policy, tracks usage, and decides whether to allow or block.

Each resource policy is resolved in this order:

1. `date_overrides["YYYY-MM-DD"]`
2. `days["monday"]` … `days["sunday"]`
3. `default`
4. legacy `weekday` / `weekend` (if present)

A resolved day policy has a `daily_limit_minutes` cap (shared across all windows; `0` means no daily cap) and `allowed_windows`. Each window needs a stable `id`, `start`, and `end` (`HH:MM`). Optional `limit_minutes` caps that window only. Daily limit always wins: leftover window budget cannot be used after the day is exhausted.

Optional `warning_minutes` on a day policy or window fire a macOS notification when remaining *usage* (not wall-clock time) first drops to that many minutes. Each threshold is sent once per resource/date/limit/window and stored in that day's usage state. Warnings are skipped when there is no corresponding limit. Notification failures are logged and never block enforcement.

Optional `display_name` is used in notification text; otherwise the resource id is used.

Usage is stored per calendar day, per resource, with totals and per-window counters keyed by window id. Changing a window's times does not reset its usage.

Invalid configs are rejected. The controller keeps running on the last valid config.

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
