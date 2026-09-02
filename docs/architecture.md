# Architecture

launchd supervises one Python controller. The controller reloads JSON configuration, evaluates weekday/weekend schedules and daily limits, invokes resource adapters for activity detection/enforcement, and stores per-day usage state. App screen time is captured by an OS `ActivityMonitor` (macOS is implemented; Windows/Linux are stubs). Website tabs are read by per-browser adapters (Chrome and Safari on macOS). Usage, window totals, browser visits, and YouTube watches are persisted in SQLite, with JSON files kept as a cache so policy, warnings, and the status page keep working.

The full design (control loop, platforms, browsers, storage, logging, and how to add apps) is in [design.md](design.md).
