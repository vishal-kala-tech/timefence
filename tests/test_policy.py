from datetime import datetime

import pytest

from timefence.policy import (
    allowed_now,
    day_policy,
    evaluate,
    in_window,
    matching_window,
    parse_hhmm,
    resolve_policy,
    _minutes,
)

MONDAY = datetime(2024, 1, 15)  # weekday 0
FRIDAY = datetime(2024, 1, 19)  # weekday 4
SATURDAY = datetime(2024, 1, 20)  # weekday 5
SUNDAY = datetime(2024, 1, 21)  # weekday 6
CHRISTMAS = datetime(2026, 12, 25, 10, 0)  # Friday

DEFAULT = {"daily_limit_minutes": 30, "allowed_windows": [{"id": "day", "start": "16:00", "end": "18:00"}]}
FRIDAY_POLICY = {"daily_limit_minutes": 60, "allowed_windows": [{"id": "friday", "start": "15:00", "end": "21:00"}]}
SATURDAY_POLICY = {"daily_limit_minutes": 90, "allowed_windows": [{"id": "sat", "start": "09:00", "end": "12:00"}]}
HOLIDAY = {"daily_limit_minutes": 180, "allowed_windows": [{"id": "holiday", "start": "00:00", "end": "24:00"}]}
WEEKDAY_POLICY = {"daily_limit_minutes": 30, "allowed_windows": [{"id": "wd", "start": "16:00", "end": "18:00"}]}
WEEKEND_POLICY = {"daily_limit_minutes": 90, "allowed_windows": [{"id": "we", "start": "09:00", "end": "12:00"}]}

HIERARCHY = {
    "policy": {
        "default": DEFAULT,
        "days": {"friday": FRIDAY_POLICY, "saturday": SATURDAY_POLICY},
        "date_overrides": {"2026-12-25": HOLIDAY},
    }
}

LEGACY = {"policy": {"weekday": WEEKDAY_POLICY, "weekend": WEEKEND_POLICY}}


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
    assert parse_hhmm(value) == expected


@pytest.mark.parametrize("value", ["1600", "9:30", "25:00", "12:60", "ab:cd", 1600, None])
def test_parse_hhmm_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        parse_hhmm(value)


def test_resolve_policy_uses_default_when_no_day_or_date_match():
    assert resolve_policy(HIERARCHY, now=MONDAY.replace(hour=12)) == DEFAULT


def test_resolve_policy_day_override_beats_default():
    assert resolve_policy(HIERARCHY, now=FRIDAY.replace(hour=12)) == FRIDAY_POLICY
    assert resolve_policy(HIERARCHY, now=SATURDAY.replace(hour=8)) == SATURDAY_POLICY


def test_resolve_policy_date_override_beats_day_and_default():
    assert resolve_policy(HIERARCHY, now=CHRISTMAS) == HOLIDAY


def test_day_policy_is_resolve_policy_alias():
    assert day_policy(HIERARCHY, now=MONDAY) == resolve_policy(HIERARCHY, now=MONDAY)


@pytest.mark.parametrize("when", [MONDAY.replace(hour=12), FRIDAY.replace(hour=23)])
def test_legacy_weekday_weekend_monday_through_friday(when):
    assert resolve_policy(LEGACY, now=when) == WEEKDAY_POLICY


@pytest.mark.parametrize("when", [SATURDAY.replace(hour=8), SUNDAY.replace(hour=23, minute=59)])
def test_legacy_weekday_weekend_saturday_and_sunday(when):
    assert resolve_policy(LEGACY, now=when) == WEEKEND_POLICY


def test_resolve_policy_fail_closed_when_missing():
    assert resolve_policy({"policy": {}}, now=MONDAY)["allowed_windows"] == []


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


def test_matching_window_returns_first_match():
    policy = {
        "allowed_windows": [
            {"id": "morning", "start": "09:00", "end": "12:00"},
            {"id": "evening", "start": "16:00", "end": "18:00"},
        ]
    }
    assert matching_window(policy, now=datetime(2024, 1, 15, 10, 0))["id"] == "morning"
    assert matching_window(policy, now=datetime(2024, 1, 15, 17, 0))["id"] == "evening"
    assert matching_window(policy, now=datetime(2024, 1, 15, 13, 0)) is None


def test_allowed_now_false_when_no_windows():
    assert allowed_now({"allowed_windows": []}, now=datetime(2024, 1, 15, 17, 0)) is False


def test_allowed_now_true_when_schedule_is_unrestricted():
    assert allowed_now({}, now=datetime(2024, 1, 15, 17, 0)) is True
    assert allowed_now({"daily_limit_minutes": 30}, now=datetime(2024, 1, 15, 17, 0)) is True


def test_evaluate_blocks_outside_window():
    policy = {"daily_limit_minutes": 45, "allowed_windows": [{"id": "after_school", "start": "16:00", "end": "18:00"}]}
    decision = evaluate(policy, {"total_usage_seconds": 0, "windows": {}}, now=datetime(2024, 1, 15, 12, 0))
    assert decision.allowed is False
    assert decision.reason == "outside_window"
    assert decision.window is None


def test_evaluate_blocks_when_daily_limit_reached_even_if_window_has_budget():
    policy = {
        "daily_limit_minutes": 45,
        "allowed_windows": [
            {"id": "after_school", "start": "16:00", "end": "18:00", "limit_minutes": 30},
            {"id": "evening", "start": "19:00", "end": "20:30", "limit_minutes": 30},
        ],
    }
    state = {
        "total_usage_seconds": 45 * 60,
        "windows": {"after_school": {"usage_seconds": 30 * 60}, "evening": {"usage_seconds": 15 * 60}},
    }
    decision = evaluate(policy, state, now=datetime(2024, 1, 15, 19, 15))
    assert decision.allowed is False
    assert decision.reason == "daily_limit"
    assert decision.window_id == "evening"


def test_evaluate_blocks_when_window_limit_reached_without_consuming_other_window():
    policy = {
        "daily_limit_minutes": 45,
        "allowed_windows": [
            {"id": "after_school", "start": "16:00", "end": "18:00", "limit_minutes": 30},
            {"id": "evening", "start": "19:00", "end": "20:30", "limit_minutes": 30},
        ],
    }
    state = {
        "total_usage_seconds": 30 * 60,
        "windows": {"after_school": {"usage_seconds": 30 * 60}},
    }
    blocked = evaluate(policy, state, now=datetime(2024, 1, 15, 16, 30))
    assert blocked.allowed is False
    assert blocked.reason == "window_limit"
    assert blocked.window_id == "after_school"

    evening = evaluate(policy, state, now=datetime(2024, 1, 15, 19, 15))
    assert evening.allowed is True
    assert evening.window_id == "evening"


def test_evaluate_allows_unlimited_window_until_daily_cap():
    policy = {
        "daily_limit_minutes": 45,
        "allowed_windows": [{"id": "after_school", "start": "16:00", "end": "18:00"}],
    }
    state = {"total_usage_seconds": 20 * 60, "windows": {"after_school": {"usage_seconds": 20 * 60}}}
    decision = evaluate(policy, state, now=datetime(2024, 1, 15, 16, 30))
    assert decision.allowed is True
    assert decision.reason == "ok"


def test_evaluate_zero_limits_mean_no_cap():
    policy = {
        "daily_limit_minutes": 0,
        "allowed_windows": [{"id": "all_day", "start": "00:00", "end": "24:00", "limit_minutes": 0}],
    }
    state = {"total_usage_seconds": 10_000, "windows": {"all_day": {"usage_seconds": 10_000}}}
    decision = evaluate(policy, state, now=datetime(2024, 1, 15, 12, 0))
    assert decision.allowed is True


def test_evaluate_unrestricted_schedule_uses_daily_limit_only():
    policy = {"daily_limit_minutes": 30}
    now = datetime(2024, 1, 15, 3, 0)
    allowed = evaluate(policy, {"total_usage_seconds": 10 * 60}, now=now)
    assert allowed.allowed is True
    assert allowed.window is None
    blocked = evaluate(policy, {"total_usage_seconds": 30 * 60}, now=now)
    assert blocked.allowed is False
    assert blocked.reason == "daily_limit"
