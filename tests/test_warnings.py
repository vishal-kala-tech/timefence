from datetime import datetime

from timefence.policy import due_warnings, warning_dialog_message
from timefence.identity import RESOURCE_TYPE_APP
from timefence.usage import add_usage, load_state, mark_warning_sent

ROBLOX = "com.roblox.RobloxPlayer"

DAILY = {
    "daily_limit_minutes": 45,
    "warning_minutes": [10, 5, 1],
    "allowed_windows": [
        {
            "id": "after_school",
            "start": "16:00",
            "end": "18:00",
            "limit_minutes": 30,
            "warning_minutes": [5, 1],
        },
        {
            "id": "evening",
            "start": "19:00",
            "end": "20:30",
            "limit_minutes": 30,
            "warning_minutes": [5, 1],
        },
    ],
}
AFTER_SCHOOL = DAILY["allowed_windows"][0]
EVENING = DAILY["allowed_windows"][1]


def keys(warnings):
    return [warning.persist_key for warning in warnings]


def test_daily_10_5_and_1_minute_warnings():
    base = {"total_usage_seconds": 0, "warnings_sent": [], "windows": {}}

    none = due_warnings(DAILY, {**base, "total_usage_seconds": 34 * 60 + 59}, label="Roblox")
    assert keys(none) == []

    ten = due_warnings(DAILY, {**base, "total_usage_seconds": 35 * 60}, label="Roblox")
    assert keys(ten) == ["daily:10"]
    assert ten[0].message == "Roblox has 10 minutes remaining today."

    five = due_warnings(DAILY, {**base, "total_usage_seconds": 40 * 60}, label="Roblox")
    assert keys(five) == ["daily:10", "daily:5"]
    assert five[1].message == "Roblox has 5 minutes remaining today."

    one = due_warnings(DAILY, {**base, "total_usage_seconds": 44 * 60}, label="Roblox")
    assert keys(one) == ["daily:10", "daily:5", "daily:1"]
    assert one[2].message == "Roblox has 1 minute remaining today."


def test_warning_fires_when_threshold_is_crossed_not_exactly_hit():
    # 5 minutes 8 seconds remaining -> should not yet warn for 5.
    before = due_warnings(DAILY, {"total_usage_seconds": 45 * 60 - (5 * 60 + 8), "warnings_sent": []})
    assert "daily:5" not in keys(before)

    # 4 minutes 53 seconds remaining -> 5-minute warning has been crossed.
    after = due_warnings(DAILY, {"total_usage_seconds": 45 * 60 - (4 * 60 + 53), "warnings_sent": []})
    assert "daily:5" in keys(after)


def test_same_warning_does_not_fire_twice():
    state = {"total_usage_seconds": 40 * 60, "warnings_sent": ["daily:10", "daily:5"]}
    assert keys(due_warnings(DAILY, state)) == []


def test_warning_state_survives_reload(tmp_path):
    when = datetime(2024, 1, 15, 16, 30)
    add_usage(tmp_path, RESOURCE_TYPE_APP, ROBLOX, 40 * 60, window_id="after_school", now=when)
    warning = due_warnings(DAILY, load_state(tmp_path, RESOURCE_TYPE_APP, ROBLOX, now=when), label="Roblox")[1]
    assert warning.persist_key == "daily:5"
    mark_warning_sent(tmp_path, RESOURCE_TYPE_APP, ROBLOX, warning, now=when)
    reloaded = load_state(tmp_path, RESOURCE_TYPE_APP, ROBLOX, now=when)
    assert reloaded["warnings_sent"] == ["daily:5"]
    assert keys(due_warnings(DAILY, reloaded)) == ["daily:10"]


def test_daily_and_window_warnings_are_independent():
    state = {
        "total_usage_seconds": 40 * 60,
        "warnings_sent": [],
        "windows": {"after_school": {"usage_seconds": 20 * 60, "warnings_sent": []}},
    }
    due = due_warnings(DAILY, state, window=AFTER_SCHOOL, label="Roblox")
    assert "daily:5" in keys(due)
    assert "5" not in keys(due)

    window_due = due_warnings(
        DAILY,
        {
            "total_usage_seconds": 20 * 60,
            "warnings_sent": [],
            "windows": {"after_school": {"usage_seconds": 25 * 60, "warnings_sent": []}},
        },
        window=AFTER_SCHOOL,
        label="Roblox",
    )
    assert "5" in keys(window_due)
    assert window_due[-1].message == "Roblox has 5 minutes remaining in the after_school window."
    assert "daily:5" not in keys(window_due)


def test_windows_keep_independent_warning_state():
    state = {
        "total_usage_seconds": 50 * 60,
        "warnings_sent": [],
        "windows": {
            "after_school": {"usage_seconds": 25 * 60, "warnings_sent": ["5"]},
            "evening": {"usage_seconds": 25 * 60, "warnings_sent": []},
        },
    }
    after_school = keys(due_warnings(DAILY, state, window=AFTER_SCHOOL))
    evening = keys(due_warnings(DAILY, state, window=EVENING))
    assert "5" not in after_school
    assert "5" in evening


def test_no_warning_when_no_limit_exists():
    policy = {"daily_limit_minutes": 0, "warning_minutes": [10, 5], "allowed_windows": []}
    assert due_warnings(policy, {"total_usage_seconds": 40 * 60, "warnings_sent": []}) == []

    window = {"id": "after_school", "warning_minutes": [5, 1]}
    assert (
        due_warnings(
            {"daily_limit_minutes": 0},
            {"total_usage_seconds": 0, "windows": {"after_school": {"usage_seconds": 25 * 60}}},
            window=window,
        )
        == []
    )


def test_new_day_resets_warning_state(tmp_path):
    yesterday = datetime(2024, 1, 15, 16, 30)
    today = datetime(2024, 1, 16, 16, 30)
    warning = due_warnings(DAILY, {"total_usage_seconds": 40 * 60, "warnings_sent": []})[1]
    mark_warning_sent(tmp_path, RESOURCE_TYPE_APP, ROBLOX, warning, now=yesterday)
    add_usage(tmp_path, RESOURCE_TYPE_APP, ROBLOX, 15, window_id="after_school", now=today)
    state = load_state(tmp_path, RESOURCE_TYPE_APP, ROBLOX, now=today)
    assert state["warnings_sent"] == []
    assert state["windows"]["after_school"]["warnings_sent"] == []


def test_warning_dialog_combines_daily_and_window_at_same_remaining():
    state = {
        "total_usage_seconds": 44 * 60,
        "warnings_sent": [],
        "windows": {"after_school": {"usage_seconds": 29 * 60, "warnings_sent": []}},
    }
    due = due_warnings(DAILY, state, window=AFTER_SCHOOL, label="YouTube")
    assert "daily:1" in keys(due)
    assert "1" in keys(due)
    assert warning_dialog_message(due, label="YouTube") == (
        "YouTube has 1 minute remaining today, including the after_school window."
    )
