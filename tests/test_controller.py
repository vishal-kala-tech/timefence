from datetime import datetime
from unittest.mock import MagicMock

import pytest

from timefence import controller
from timefence.policy import allowed_now as real_allowed_now
from timefence.policy import day_policy as real_day_policy
from timefence.usage import add_usage, get_usage
from tests.helpers import make_config, make_policy, make_resource, write_rules

MONDAY_AFTERNOON = datetime(2024, 1, 15, 16, 30)
SATURDAY_MORNING = datetime(2024, 1, 20, 10, 0)


class LoopStop(BaseException):
    """Stop the controller after N sleep calls without being swallowed by except Exception."""


def freeze_policy_now(monkeypatch, when):
    monkeypatch.setattr(
        controller,
        "day_policy",
        lambda resource, now=None: real_day_policy(resource, now=when),
    )
    monkeypatch.setattr(
        controller,
        "allowed_now",
        lambda policy, now=None: real_allowed_now(policy, now=when),
    )


def stop_after(n=1):
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        if len(slept) >= n:
            raise LoopStop()

    return slept, sleep


def run_cycles(app_dir, monkeypatch, cycles=1):
    slept, sleep = stop_after(cycles)
    monkeypatch.setattr(controller.time, "sleep", sleep)
    with pytest.raises(LoopStop):
        controller.run(app_dir)
    return slept


def install_modules(monkeypatch, **active):
    modules = {}
    for name, is_active in active.items():
        mod = MagicMock()
        mod.is_active.return_value = is_active
        modules[name] = mod
    monkeypatch.setattr(controller, "MODULES", modules)
    return modules


def test_skips_disabled_and_unknown_resources(app_dir, monkeypatch):
    freeze_policy_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True, youtube=True)
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(enabled=False),
                "youtube": make_resource(enabled=True),
                "netflix": make_resource(enabled=True),
            }
        ),
    )

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].is_active.assert_not_called()
    modules["roblox"].enforce.assert_not_called()
    modules["youtube"].is_active.assert_called_once()
    modules["youtube"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox") == 0
    assert get_usage(app_dir / "state", "youtube") == 15


def test_inactive_resource_is_not_counted_or_blocked(app_dir, monkeypatch):
    freeze_policy_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=False)
    write_rules(app_dir, make_config())

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox") == 0


def test_active_in_window_under_limit_records_usage(app_dir, monkeypatch):
    freeze_policy_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            check_interval_seconds=20,
            resources={"roblox": make_resource(weekday=make_policy(daily_limit_minutes=30))},
        ),
    )

    slept = run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox") == 20
    assert slept == [20]


def test_active_outside_window_is_blocked_without_usage(app_dir, monkeypatch):
    freeze_policy_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={"roblox": make_resource(weekday=make_policy(allowed_windows=[]))}
        ),
    )

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_called_once()
    assert get_usage(app_dir / "state", "roblox") == 0


def test_active_at_daily_limit_is_blocked(app_dir, monkeypatch):
    freeze_policy_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={"roblox": make_resource(weekday=make_policy(daily_limit_minutes=1))}
        ),
    )
    add_usage(app_dir / "state", "roblox", 60)

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_called_once()
    assert get_usage(app_dir / "state", "roblox") == 60


def test_zero_daily_limit_means_no_cap(app_dir, monkeypatch):
    freeze_policy_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={"roblox": make_resource(weekday=make_policy(daily_limit_minutes=0))}
        ),
    )
    add_usage(app_dir / "state", "roblox", 10_000)

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox") == 10_015


def test_weekend_policy_is_selected(app_dir, monkeypatch):
    freeze_policy_now(monkeypatch, SATURDAY_MORNING)
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    weekday=make_policy(allowed_windows=[]),
                    weekend=make_policy(daily_limit_minutes=90),
                )
            }
        ),
    )

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox") == 15


def test_revision_change_is_logged_once(app_dir, monkeypatch, caplog):
    freeze_policy_now(monkeypatch, MONDAY_AFTERNOON)
    install_modules(monkeypatch, roblox=False)
    write_rules(app_dir, make_config(revision=4))

    import logging

    caplog.set_level(logging.INFO)
    run_cycles(app_dir, monkeypatch, cycles=2)

    messages = [r.getMessage() for r in caplog.records if "Loaded config revision" in r.getMessage()]
    assert messages == ["Loaded config revision 4"]


def test_cycle_failure_uses_default_interval_then_continues(app_dir, monkeypatch, caplog):
    freeze_policy_now(monkeypatch, MONDAY_AFTERNOON)
    install_modules(monkeypatch, roblox=False)

    calls = {"n": 0}

    def flaky_load(_path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return make_config(check_interval_seconds=9)

    monkeypatch.setattr(controller, "load_config", flaky_load)
    import logging

    caplog.set_level(logging.ERROR)
    slept = run_cycles(app_dir, monkeypatch, cycles=2)

    assert slept == [15, 9]
    assert any("Controller cycle failed" in r.getMessage() for r in caplog.records)


def test_one_resource_failure_skips_remaining_resources_that_cycle(app_dir, monkeypatch):
    freeze_policy_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True, youtube=True)
    modules["roblox"].is_active.side_effect = RuntimeError("pgrep failed")
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(),
                "youtube": make_resource(),
            }
        ),
    )

    run_cycles(app_dir, monkeypatch)

    modules["youtube"].is_active.assert_not_called()
