# TimeFence

macOS parental-control prototype with a Python controller and JSON configuration designed for eventual remote/API updates.

Design: [docs/design.md](docs/design.md).

## Policy model
JSON is the source of truth. Resource modules only detect activity and enforce blocks. The controller resolves policy, tracks usage, and decides whether to allow or block.

Each resource policy is resolved in this order:

1. `date_overrides["YYYY-MM-DD"]`
2. `days["monday"]` … `days["sunday"]`
3. `default`
4. legacy `weekday` / `weekend` (if present)

A resolved day policy has a `daily_limit_minutes` cap (shared across all windows; `0` means no daily cap) and `allowed_windows`. Each window needs a stable `id`, `start`, and `end` (`HH:MM`). Optional `limit_minutes` caps that window only. Daily limit always wins: leftover window budget cannot be used after the day is exhausted.

Optional `warning_minutes` on a day policy or window fire the same 6-second countdown window when remaining *usage* (not wall-clock time) first drops to that many minutes. Each threshold is sent once per resource/date/limit/window and stored in that day's usage state. Warnings are skipped when there is no corresponding limit. Notification failures are logged and never block enforcement.

Just before a block, TimeFence shows one 6-second countdown window (the remaining seconds update in the text; there is no action button). When it closes, YouTube matching tabs are closed or Roblox is terminated.

Optional `display_name` is used in notification text; otherwise the resource id is used.

Usage is stored per calendar day, per resource, with totals and per-window counters keyed by window id. Changing a window's times does not reset its usage. Each save also writes a pipe-separated table for Excel at `state/YYYY-MM-DD.txt` (daily and window totals plus YouTube video rows). Import with delimiter `|`. `./scripts/budget.sh` prints allowed vs remaining time for each enabled resource.

The child can check today's used and remaining time in a browser at `http://127.0.0.1:8743/` (only on that Mac). The page also lists the top 10 websites from today's frontmost-browser tab log. It refreshes every 15 seconds. `./scripts/today.sh` opens it. A copy is also written to `~/Library/Application Support/TimeFence/status.html`. Set `status_page` to `false` in `rules.json` to turn this off, or `status_port` to use a different localhost port.

Parents set standing limits and grant extra time at `http://127.0.0.1:8743/setup` (PIN-gated; the kid page does not link here). First visit chooses a PIN; later visits unlock with it. The same screen is used for first-time setup and ongoing edits. Bonus time is for the current day only. `./scripts/setup.sh` opens the parent page. The CLI still works: `./scripts/grant.sh youtube 15` (or `roblox`, `youtube_shorts`). `./scripts/grant.sh --list` shows active bonuses; `./scripts/grant.sh youtube --clear` removes one. The kid page shows “Bonus until …”.

When a configured browser is frontmost, TimeFence also logs the active tab (host, URL, title, time on that URL) without applying a budget. Consecutive polls of the same URL collapse into one row. Files are `state/browse/YYYY-MM-DD.json` and a pipe-separated `state/browse/YYYY-MM-DD.txt` for Excel. `./scripts/sites.sh` prints today's list. `./scripts/activity.sh` summarizes videos and websites in English. Set `log_browsing` to `false` in `rules.json` to turn this off. This log is for later policy design; it does not block sites.

YouTube watch and Shorts keep a `videos` list in that day's state in the exact order videos were on the front tab. Each row has video id, title, channel, canonical URL, first/last seen time, and seconds. Channel name comes from YouTube's public oEmbed API (no key). The last 20 successful lookups are cached in memory so a video watched across 15-second polls does not refetch. `./scripts/watched.sh` prints today's history. `./scripts/activity.sh` summarizes that history in English.

Invalid configs are rejected. The controller keeps running on the last valid config.

## Config
Standing limits live in `config/rules.json`. Use the parent setup page for first-time setup and later changes; the controller reloads the file every cycle. `revision` increments on each save from the parent page. You can still edit the JSON directly. An eventual API/sync agent can atomically replace this file after validating a downloaded config.

## Install
On a Mac that already has Python 3.10+:

`./scripts/install.sh`

On a Mac with no Python (from-scratch): copy this TimeFence folder onto the Mac, then:

```bash
cd timefence
./scripts/bootstrap.sh
```

That installs Python 3.13 from python.org if needed (administrator password), then runs `install.sh`. Internet is required for the Python download. Homebrew is used instead when `brew` is already present.

Runtime files are installed under `~/Library/Application Support/TimeFence`, logs under `~/Library/Logs/TimeFence`, and the LaunchAgent under `~/Library/LaunchAgents`. Keep the TimeFence project folder so helper scripts (`budget.sh`, `activity.sh`, `status.sh`) remain available.

## Current resources
- Apps (bundle ID on macOS): Roblox, Cursor, Visual Studio / VS Code, Chrome, Safari (`com.apple.Safari`), and PyCharm. Counts **foreground** time only. Idle time over `screen_time.idle_threshold_seconds` (default 120), screen lock, sleep, and poll gaps longer than `max_countable_interval_seconds` (default 30) are not counted. Background processes do not use budget. Cursor, Visual Studio, Chrome, Safari, and PyCharm ship with no daily cap (`daily_limit_minutes: 0`) so they are tracked without being blocked. Add another Mac app by copying one of these resources and setting `type` to `"app"` plus `bundle_ids`. Roblox still uses its standing windows and daily limit. On Windows/Linux, use `app_ids.win32` / `app_ids.linux` once those platform adapters are implemented.
- YouTube: active-tab detection and tab closing via browser adapters. macOS ships Chrome and Safari. Regular watch (`youtube.com/watch`, `youtu.be/`) and Shorts (`youtube.com/shorts`) are separate resources. Set `browsers` on a website resource (default Chrome only if omitted). A paused YouTube player does not consume budget (Chrome/Safari need “Allow JavaScript from Apple Events”). Website-level activity is not inferred from the frontmost app; a future browser extension can feed the same usage tracker.

## Future API flow
Remote API -> download candidate JSON -> validate -> write temporary file -> atomic rename to `rules.json` -> controller reloads next cycle.
