from datetime import datetime

DAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_EMPTY_POLICY = {"daily_limit_minutes": 0, "allowed_windows": []}


class Evaluation:
    def __init__(self, allowed, reason, window=None):
        self.allowed = allowed
        self.reason = reason
        self.window = window

    @property
    def window_id(self):
        if not self.window:
            return None
        return self.window.get("id")


def parse_hhmm(value):
    if not isinstance(value, str) or value.count(":") != 1:
        raise ValueError(f"Invalid time {value!r}; expected HH:MM")

    hours_s, minutes_s = value.split(":")
    if not (hours_s.isdigit() and minutes_s.isdigit() and len(hours_s) == 2 and len(minutes_s) == 2):
        raise ValueError(f"Invalid time {value!r}; expected HH:MM")

    hours, minutes = int(hours_s), int(minutes_s)
    if hours == 24 and minutes == 0:
        return 24 * 60
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"Invalid time {value!r}; expected HH:MM")
    return hours * 60 + minutes


def _minutes(s):
    return parse_hhmm(s)


def limit_seconds(minutes):
    if minutes in (None, 0):
        return 0
    return int(float(minutes) * 60)


def limit_label(seconds):
    return f"{seconds}s" if seconds else "none"


def resolve_policy(resource, now=None):
    now = now or datetime.now()
    policy = resource.get("policy") or {}
    if not isinstance(policy, dict):
        return dict(_EMPTY_POLICY)

    date_overrides = policy.get("date_overrides") or {}
    if isinstance(date_overrides, dict):
        override = date_overrides.get(now.date().isoformat())
        if isinstance(override, dict):
            return override

    days = policy.get("days") or {}
    if isinstance(days, dict):
        named = days.get(DAY_NAMES[now.weekday()])
        if isinstance(named, dict):
            return named

    default = policy.get("default")
    if isinstance(default, dict):
        return default

    legacy_key = "weekend" if now.weekday() >= 5 else "weekday"
    legacy = policy.get(legacy_key)
    if isinstance(legacy, dict):
        return legacy

    return dict(_EMPTY_POLICY)


def day_policy(resource, now=None):
    return resolve_policy(resource, now=now)


def in_window(window, now=None):
    now = now or datetime.now()
    cur = now.hour * 60 + now.minute
    start = parse_hhmm(window["start"])
    end = parse_hhmm(window["end"])
    return start <= cur < end if start <= end else cur >= start or cur < end


def matching_window(policy, now=None):
    now = now or datetime.now()
    for window in policy.get("allowed_windows") or []:
        if in_window(window, now):
            return window
    return None


def allowed_now(policy, now=None):
    return matching_window(policy, now=now) is not None


def evaluate(policy, state, now=None):
    window = matching_window(policy, now=now)
    if window is None:
        return Evaluation(False, "outside_window")

    used = int((state or {}).get("total_usage_seconds", 0))
    daily_limit = limit_seconds(policy.get("daily_limit_minutes"))
    if daily_limit and used >= daily_limit:
        return Evaluation(False, "daily_limit", window)

    windows = (state or {}).get("windows") or {}
    window_used = int((windows.get(window.get("id")) or {}).get("usage_seconds", 0))
    window_limit = limit_seconds(window.get("limit_minutes"))
    if window_limit and window_used >= window_limit:
        return Evaluation(False, "window_limit", window)

    return Evaluation(True, "ok", window)
