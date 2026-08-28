from datetime import datetime


def day_policy(resource, now=None):
    now = now or datetime.now()
    key = "weekend" if now.weekday() >= 5 else "weekday"
    return resource["policy"][key]


def _minutes(s):
    h, m = map(int, s.split(":"))
    return h * 60 + m


def in_window(window, now=None):
    now = now or datetime.now()
    cur = now.hour * 60 + now.minute
    start = _minutes(window["start"])
    end = _minutes(window["end"])
    return start <= cur < end if start <= end else cur >= start or cur < end


def allowed_now(policy, now=None):
    return any(in_window(w, now) for w in policy.get("allowed_windows", []))
