# Architecture

launchd supervises one Python controller. The controller reloads JSON configuration, evaluates weekday/weekend schedules and daily limits, invokes resource adapters for activity detection/enforcement, and stores per-day usage state. App screen time is captured from the macOS frontmost bundle ID plus HID idle time, persisted in SQLite sessions/daily totals, then synced into the existing JSON usage files so policy, warnings, and the status page keep working. Shell is retained only for installation and launchd lifecycle management.

The full design (control loop, what counts, storage, logging, and how to add apps) is in [design.md](design.md).
