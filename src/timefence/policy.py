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


def resource_label(name, resource=None):
    if isinstance(resource, dict):
        for key in ("display_name", "label", "name"):
            value = resource.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return name


def _minutes_text(minutes):
    if float(minutes) == int(minutes):
        minutes = int(minutes)
    unit = "minute" if float(minutes) == 1 else "minutes"
    return f"{minutes} {unit}"


def normalize_warning_minutes(values):
    if not values:
        return []
    out = []
    seen = set()
    for value in values:
        key = float(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


class LimitWarning:
    def __init__(self, persist_key, minutes, message, window_id=None):
        self.persist_key = persist_key
        self.minutes = minutes
        self.message = message
        self.window_id = window_id


def _crossed_thresholds(limit, used, warning_minutes, sent, persist_key, message, window_id=None):
    if not limit:
        return []
    remaining = limit - int(used or 0)
    due = []
    sent_keys = {str(item) for item in (sent or [])}
    for minutes in normalize_warning_minutes(warning_minutes):
        warn_seconds = limit_seconds(minutes)
        if warn_seconds <= 0 or remaining <= 0 or remaining > warn_seconds:
            continue
        key = persist_key(minutes)
        if key in sent_keys:
            continue
        due.append(LimitWarning(key, minutes, message(minutes), window_id=window_id))
        sent_keys.add(key)
    return due


def due_warnings(policy, state, window=None, label="resource"):
    state = state or {}
    due = []
    due.extend(
        _crossed_thresholds(
            limit_seconds(policy.get("daily_limit_minutes")),
            state.get("total_usage_seconds", 0),
            policy.get("warning_minutes"),
            state.get("warnings_sent"),
            persist_key=lambda minutes: f"daily:{int(minutes) if float(minutes) == int(minutes) else minutes}",
            message=lambda minutes: f"{label} has {_minutes_text(minutes)} remaining today.",
        )
    )
    if window:
        window_id = window.get("id")
        window_state = (state.get("windows") or {}).get(window_id) or {}
        due.extend(
            _crossed_thresholds(
                limit_seconds(window.get("limit_minutes")),
                window_state.get("usage_seconds", 0),
                window.get("warning_minutes"),
                window_state.get("warnings_sent"),
                persist_key=lambda minutes: str(int(minutes) if float(minutes) == int(minutes) else minutes),
                message=lambda minutes: (
                    f"{label} has {_minutes_text(minutes)} remaining in the {window_id} window."
                ),
                window_id=window_id,
            )
        )
    return due


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
