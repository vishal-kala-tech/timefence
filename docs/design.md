# TimeFence design

TimeFence is a macOS parental-control agent. It measures **active foreground time** for configured apps and websites, applies JSON policy (schedules, daily limits, warnings), and enforces blocks. This document describes the current design: what is counted, what is not, and how the pieces fit together.

Operator setup and day-to-day use live in [README.md](../README.md). This file is the engineering design.

## Goals

- Track how long a child actively uses configured Mac apps (Roblox, Discord, Cursor, Chrome, …) and websites (YouTube watch vs Shorts).
- Count only **foreground, non-idle** time. Background processes and idle keyboard/mouse time do not consume budget.
- Keep policy in JSON so limits can change without code, including later remote/API updates.
- Separate detection, usage accounting, policy, and enforcement so each can be replaced.
- Survive sleep, process restarts, and calendar-day rollover without inflating totals or erasing history.
- Keep existing YouTube tab tracking, grants, status page, and parent setup working.

## Non-goals (current)

- Windows / Linux.
- Inferring the active website from Chrome or Safari. Website activity today comes from AppleScript on the Chrome front tab. A future browser extension can feed the same usage tracker.
- Network-level blocking, MDM, or Screen Time API integration.
- Overwriting a parent-edited live `rules.json` on reinstall.

## Runtime

`launchd` keeps one Python process alive in the Aqua (logged-in) session.

```text
launchd (com.user.timefence)
  └── python -m timefence.main
        └── controller.run(TIME_FENCE_HOME)
```

| Path | Role |
|---|---|
| Project `timefence/` | Source and helper scripts |
| `~/Library/Application Support/TimeFence/` | Installed copy: `src/`, `config/rules.json`, `state/` |
| `~/Library/Logs/TimeFence/timefence.err.log` | INFO/WARNING logs (stderr) |
| `~/Library/LaunchAgents/com.user.timefence.plist` | Agent definition |

`PYTHONPATH` points at the **installed** `src/`, not the git checkout. `install.sh` copies `src/` into Application Support and **does not replace** an existing `config/rules.json`. New app resources and `bundle_ids` must be merged into the live file (or the live file replaced) after install.

## Responsibilities

```text
ActivityMonitor     detect frontmost app, HID idle, lock
UsageTracker        sessions, elapsed time, daily totals
UsageStore          persist usage (SQLite today)
JSON usage files    policy/status/grants still read these
RuleEngine/policy   allow / warn / block
EnforcementService  quit app or close matching tabs
Resource adapters   inspect + enforce for a type (app, website)
```

The controller is the only loop. It reloads `rules.json` every cycle, records activity, evaluates policy, then enforces.

## Control loop

Each cycle:

1. Load and validate `config/rules.json`. On invalid JSON, keep the last valid config.
2. Optionally log the Chrome front tab (`log_browsing`).
3. If screen-time capture is enabled and any resource is an app (`type: "app"` or `bundle_ids`):
   - Snapshot frontmost app + idle + lock.
   - Match bundle ID to a resource.
   - Credit **actual elapsed seconds** since the previous poll (not the configured interval).
   - Write SQLite, then add the same seconds to the JSON usage file.
   - Evaluate policy and emit warnings.
4. For each resource:
   - **App capture resources:** enforce only if the process is still running and policy says block. Do not add usage again.
   - **Website resources (YouTube):** existing inspect → evaluate → add interval seconds if allowed → enforce.
5. Refresh the local status page.

Poll interval is `screen_time.poll_interval_seconds` when set, otherwise `check_interval_seconds`.

## Screen-time capture

### What counts

Only the **frontmost** configured app, and only while:

- the user has not been idle longer than `idle_threshold_seconds` (HID keyboard/mouse, default 120s)
- the screen does not look locked (`loginwindow` / screensaver bundle, or an injected lock flag)
- elapsed time since the last poll is greater than 0 and **≤ `max_countable_interval_seconds`** (default 30s)

The last rule is the sleep/suspension guard. A 10-minute gap after lid-close is an interruption, not 10 minutes of Roblox.

Two configured apps never accumulate at once. If Roblox is running in the background and Chrome is frontmost, only Chrome (if configured) is counted.

### Identification

Bundle ID is canonical. Process name is fallback for `pgrep` / `pkill` only.

```text
frontmost bundle_id  →  find_resource_by_bundle_id(resources)
```

Unknown bundle IDs produce a frontmost log with `resource=none` and do not start a session.

Shipped app IDs:

| Resource | Bundle IDs |
|---|---|
| roblox | `com.roblox.RobloxPlayer`, `com.roblox.Roblox` |
| cursor | `com.todesktop.230313mzl4w4u92` |
| visual_studio | `com.microsoft.VSCode`, `com.microsoft.VSCodeInsiders`, `com.microsoft.visual-studio` |
| chrome | `com.google.Chrome`, `com.google.Chrome.beta`, `com.google.Chrome.canary` |
| pycharm | `com.jetbrains.pycharm`, `com.jetbrains.pycharm.ce` |

Add an app by copying one of these resources: `type: "app"` plus `bundle_ids`. No code change.

Cursor / VS / Chrome / PyCharm ship with `daily_limit_minutes: 0` (track, do not block). Roblox keeps standing windows and a daily cap.

### macOS APIs

| Signal | Preferred | Fallback |
|---|---|---|
| Frontmost app | `NSWorkspace.shared.frontmostApplication` (optional PyObjC) | System Events AppleScript (`timeout 5`) |
| Idle time | `CGEventSourceSecondsSinceLastEventType` via ctypes | `ioreg` HIDIdleTime |
| Lock | Frontmost bundle `com.apple.loginwindow` | Large poll gap after sleep |

Optional extra: `pip install "timefence[macos]"` for PyObjC. Not required.

### Sessions

A session starts when a configured resource becomes the foreground active app.

It ends when another app becomes foreground, the user goes idle past the threshold, the screen locks, the poll gap exceeds the safe maximum, the app is no longer matched, or TimeFence stops.

On agent start, any SQLite session with `ended_at IS NULL` is closed without adding the downtime. Daily totals stay.

Midnight splits a countable interval across two dates. Yesterday’s row is kept; today starts at zero.

### Activity model (future sources)

```text
Activity.kind = app | website | media
Activity.identifier = bundle ID | URL | (later) media id
```

`UsageTracker.apply()` does not care whether the observation came from NSWorkspace or a browser extension. Website matching via `url_contains` / `url_excludes` is already implemented for that path; the monitor does not call it yet.

## Website path (YouTube)

Unchanged from the original controller design:

- AppleScript reads the Chrome **front** window’s active tab.
- `url_contains` / `url_excludes` select watch vs Shorts.
- Paused player (`playback: paused`) does not add usage; time-of-day blocks still apply.
- Enforcement closes matching tabs only.

Chrome-as-app and YouTube-as-website are different resources. Foreground Chrome can increment `chrome` while a YouTube tab can also increment `youtube`. That is intentional: one is “time in Chrome”, the other is “time on YouTube”.

## Policy

JSON is the source of truth. Resolution order for a resource:

1. `policy.date_overrides["YYYY-MM-DD"]`
2. `policy.days["monday"]` … `"sunday"`
3. `policy.default`
4. legacy `weekday` / `weekend`

A day policy may include:

- `daily_limit_minutes` — `0` or omitted means no daily cap
- `allowed_windows` — if the key is **missing**, the day is unrestricted (limit only). If it is `[]`, nothing is allowed except an active bonus grant.
- `warning_minutes` — fire once per resource/date when remaining usage first drops to that many minutes

Evaluate after adding screen-time usage. Reasons: `ok`, `outside_window`, `daily_limit`, `window_limit`. Daily limit always wins over leftover window budget.

Same-day bonus grants (`grants.json`) extend limits and can open a bonus window. They expire at end of local day.

## Enforcement

Adapters own the mechanism:

- Generic app / Roblox: quit by bundle ID, else `pkill` `process_pattern`
- YouTube: close matching Chrome tabs

The controller shows a 6-second countdown, then calls `EnforcementService`. Notification failure never skips the block.

Background Roblox outside a window is still killed even though it did not consume budget.

## Storage

### SQLite — `state/screen_time.sqlite`

Screen-time source of truth for sessions and app daily totals. Monitoring code depends on `UsageStore`, not SQLite, so the backend can be replaced.

```sql
daily_usage (usage_date, resource_id, total_active_seconds, updated_at)
usage_sessions (id, resource_id, started_at, ended_at, duration_seconds, activity_kind, identifier)
warning_state (usage_date, resource_id, warning_key)   -- e.g. limit_reached once per day
```

### JSON — `state/<resource>/<YYYY-MM-DD>.json`

Existing per-resource day files: `total_usage_seconds`, per-window counters, `warnings_sent`, YouTube `videos`. Status page, budget, grants, and website tracking still use these. Screen-time ticks dual-write here so those surfaces stay consistent.

`state/YYYY-MM-DD.txt` is a pipe-separated Excel export. `state/browse/` is the unrestricted Chrome tab log (not a budget).

Query helpers on `UsageTracker`: `get_today_usage`, `get_all_today_usage`, `get_remaining_seconds`, `get_current_activity`, `get_current_session`.

## Logging

Look in **`timefence.err.log`**. Python `INFO` is stderr.

| Event | When |
|---|---|
| `Loaded config revision N` | Live `rules.json` revision changed |
| `SCREEN_TIME_ENABLED` | Same; lists poll interval, idle threshold, app resource ids |
| `SCREEN_TIME_FRONTMOST` | Frontmost app **changed** (including unmatched `resource=none`) |
| `SCREEN_TIME_SESSION_STARTED` / `_ENDED` | Configured resource session boundaries |
| `SCREEN_TIME_USAGE` | Countable increment |
| `SCREEN_TIME_IDLE` | Crossed idle threshold |
| `SCREEN_TIME_LIMIT_REACHED` | Daily limit first hit that day |

Frontmost is not logged every poll. Usage is logged when seconds are added.

## Package layout

```text
src/timefence/
  controller.py              loop, wiring
  config.py                  validate rules.json
  policy.py                  windows, limits, warnings
  usage.py                   JSON day state
  activity/                  frontmost, idle, bundle matching
  tracking/                  UsageStore, SQLite, UsageTracker
  models/                    Activity, FrontmostApp, usage DTOs
  resources/app.py           generic app inspect/enforce
  resources/roblox.py        Roblox pgrep/pkill (legacy + enforce)
  resources/youtube.py       Chrome tab inspect/close
  rules/rule_engine.py       thin policy facade
  enforcement/               adapter.enforce()
  grants.py, budget.py, status_page.py, parent_*
```

## Adding a Mac app

1. Add a resource to the **live** `~/Library/Application Support/TimeFence/config/rules.json` (not only the git copy).
2. Set `"type": "app"` and `"bundle_ids": ["com.example.App"]`.
3. Set policy (`daily_limit_minutes: 0` to track only).
4. Confirm with `PYTHONPATH=src python -m timefence.activity` that the frontmost bundle ID matches.
5. Watch `timefence.err.log` for `SCREEN_TIME_SESSION_STARTED resource=…`.

`install.sh` will not add that resource for you if a live `rules.json` already exists.

## Future

- Browser extension posts `Activity(kind=website, identifier=url)` into `UsageTracker` (same sessions/daily tables).
- Remote config: download → validate → atomic replace of `rules.json` → next cycle reloads.
- Replace SQLite `UsageStore` without changing the monitor.
- Optional tighter lock detection if PyObjC Quartz is present; sleep is already covered by the max countable interval.
