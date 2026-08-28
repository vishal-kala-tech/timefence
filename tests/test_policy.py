from datetime import datetime

import pytest

from timefence.policy import allowed_now, day_policy, in_window, _minutes

MONDAY = datetime(2024, 1, 15)  # weekday 0
FRIDAY = datetime(2024, 1, 19)  # weekday 4
SATURDAY = datetime(2024, 1, 20)  # weekday 5
SUNDAY = datetime(2024, 1, 21)  # weekday 6

WEEKDAY_POLICY = {"daily_limit_minutes": 30, "allowed_windows": [{"start": "16:00", "end": "18:00"}]}
WEEKEND_POLICY = {"daily_limit_minutes": 90, "allowed_windows": [{"start": "09:00", "end": "12:00"}]}
RESOURCE = {"policy": {"weekday": WEEKDAY_POLICY, "weekend": WEEKEND_POLICY}}


@pytest.mark.parametrize(
    "value,expected",
    [
        ("00:00", 0),
        ("00:01", 1),
        ("09:30", 570),
        ("16:00", 960),
        ("23:59", 1439),
        ("24:00", 1440),
    ],
)
def test_minutes_parses_hh_mm(value, expected):
    assert _minutes(value) == expected


def test_minutes_rejects_missing_separator():
    with pytest.raises(ValueError):
        _minutes("1600")


@pytest.mark.parametrize("when", [MONDAY.replace(hour=12), FRIDAY.replace(hour=23)])
def test_day_policy_uses_weekday_monday_through_friday(when):
    assert day_policy(RESOURCE, now=when) == WEEKDAY_POLICY


@pytest.mark.parametrize("when", [SATURDAY.replace(hour=8), SUNDAY.replace(hour=23, minute=59)])
def test_day_policy_uses_weekend_saturday_and_sunday(when):
    assert day_policy(RESOURCE, now=when) == WEEKEND_POLICY


@pytest.mark.parametrize(
    "now,expected",
    [
        (datetime(2024, 1, 15, 15, 59), False),
        (datetime(2024, 1, 15, 16, 0), True),
        (datetime(2024, 1, 15, 17, 59), True),
        (datetime(2024, 1, 15, 18, 0), False),
        (datetime(2024, 1, 15, 18, 1), False),
    ],
)
def test_in_window_is_inclusive_at_start_exclusive_at_end(now, expected):
    assert in_window({"start": "16:00", "end": "18:00"}, now=now) is expected


@pytest.mark.parametrize(
    "now,expected",
    [
        (datetime(2024, 1, 15, 21, 59), False),
        (datetime(2024, 1, 15, 22, 0), True),
        (datetime(2024, 1, 15, 23, 59), True),
        (datetime(2024, 1, 16, 0, 0), True),
        (datetime(2024, 1, 16, 5, 59), True),
        (datetime(2024, 1, 16, 6, 0), False),
        (datetime(2024, 1, 16, 12, 0), False),
    ],
)
def test_in_window_handles_overnight_wraparound(now, expected):
    assert in_window({"start": "22:00", "end": "06:00"}, now=now) is expected


def test_in_window_same_start_and_end_never_matches():
    assert in_window({"start": "00:00", "end": "00:00"}, now=datetime(2024, 1, 15, 0, 0)) is False
    assert in_window({"start": "12:00", "end": "12:00"}, now=datetime(2024, 1, 15, 12, 0)) is False


def test_in_window_all_day_with_24_00():
    for hour in range(24):
        now = datetime(2024, 1, 15, hour, 30 if hour < 23 else 59)
        assert in_window({"start": "00:00", "end": "24:00"}, now=now) is True


def test_allowed_now_false_when_no_windows():
    assert allowed_now({"allowed_windows": []}, now=datetime(2024, 1, 15, 17, 0)) is False
    assert allowed_now({}, now=datetime(2024, 1, 15, 17, 0)) is False


def test_allowed_now_true_if_any_window_matches():
    policy = {
        "allowed_windows": [
            {"start": "09:00", "end": "10:00"},
            {"start": "16:00", "end": "18:00"},
        ]
    }
    assert allowed_now(policy, now=datetime(2024, 1, 15, 9, 30)) is True
    assert allowed_now(policy, now=datetime(2024, 1, 15, 17, 0)) is True
    assert allowed_now(policy, now=datetime(2024, 1, 15, 12, 0)) is False
