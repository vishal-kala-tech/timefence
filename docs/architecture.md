# Architecture
launchd supervises one Python controller. The controller reloads JSON configuration, evaluates weekday/weekend schedules and daily limits, invokes resource adapters for activity detection/enforcement, and stores per-day usage state. Shell is retained only for installation and launchd lifecycle management.
