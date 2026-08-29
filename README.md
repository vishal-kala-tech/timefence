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

Optional `warning_minutes` on a day policy or window fire the same 6-second countdown window when remaining *usage* (not wall-clock time) first drops to that many minutes. Each threshold is sent once per resource/date/limit/window and stored in that day's usage state. Warnings are skipped when there is no corresponding limit. Notification failures are logged and never block enforcement.

Just before a block, TimeFence shows one 6-second countdown window (the remaining seconds update in the text; there is no action button). When it closes, YouTube matching tabs are closed or Roblox is terminated.

Optional `display_name` is used in notification text; otherwise the resource id is used.

Usage is stored per calendar day, per resource, with totals and per-window counters keyed by window id. Changing a window's times does not reset its usage. Each save also writes a pipe-separated table for Excel at `state/YYYY-MM-DD.txt` (daily and window totals plus YouTube video rows). Import with delimiter `|`. `./scripts/budget.sh` prints allowed vs remaining time for each enabled resource.

The child can check today's used and remaining time in a browser at `http://127.0.0.1:8743/` (only on that Mac). The page also lists the top 10 websites from today's Chrome active-tab log. It refreshes every 15 seconds. `./scripts/today.sh` opens it. A copy is also written to `~/Library/Application Support/TimeFence/status.html`. Set `status_page` to `false` in `rules.json` to turn this off, or `status_port` to use a different localhost port.

A parent can add extra time for the current session without editing `rules.json`: `./scripts/grant.sh youtube 15` (or `roblox`, `youtube_shorts`). That lasts until now plus those minutes, or midnight, whichever is sooner. It raises the standing cap and, if needed, allows the resource outside a normal window. `./scripts/grant.sh --list` shows active bonuses; `./scripts/grant.sh youtube --clear` removes one. The kid page shows “Bonus until …”.

When Chrome is frontmost, TimeFence also logs the active tab (host, URL, title, time on that URL) without applying a budget. Consecutive polls of the same URL collapse into one row. Files are `state/browse/YYYY-MM-DD.json` and a pipe-separated `state/browse/YYYY-MM-DD.txt` for Excel. `./scripts/sites.sh` prints today's list. `./scripts/activity.sh` summarizes videos and websites in English. Set `log_browsing` to `false` in `rules.json` to turn this off. This log is for later policy design; it does not block sites.

YouTube watch and Shorts keep a `videos` list in that day's state in the exact order videos were on the front tab. Each row has video id, title, channel, canonical URL, first/last seen time, and seconds. Channel name comes from YouTube's public oEmbed API (no key). The last 20 successful lookups are cached in memory so a video watched across 15-second polls does not refetch. `./scripts/watched.sh` prints today's history. `./scripts/activity.sh` summarizes that history in English.

Invalid configs are rejected. The controller keeps running on the last valid config.

## Config
Edit `config/rules.json`. The controller reloads it every cycle, so an eventual API/sync agent can atomically replace this file after validating a downloaded config. `revision` makes remote changes easy to identify.

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
- Roblox: counts time only while a matching app is frontmost; a background Roblox process does not use budget. Blocks still quit Roblox if it is running outside a window or over the limit.
- YouTube: Google Chrome active-tab detection and tab closing via AppleScript. Regular watch (`youtube.com/watch`, `youtu.be/`) and Shorts (`youtube.com/shorts`) are separate resources with their own limits. Optional `url_contains` / `url_excludes` on a website resource control which tabs count; blocking closes only matching tabs. A paused YouTube player does not consume budget (Chrome needs View → Developer → Allow JavaScript from Apple Events). Time-of-day blocks still apply while paused.

## Future API flow
Remote API -> download candidate JSON -> validate -> write temporary file -> atomic rename to `rules.json` -> controller reloads next cycle.
