from datetime import datetime
from unittest.mock import MagicMock

import pytest

from timefence import controller
from timefence.grants import apply_grant
from timefence.policy import resolve_policy
from timefence.usage import add_usage, get_usage, load_state
from tests.helpers import (
    make_config,
    make_day_policy,
    make_resource,
    make_window,
    write_rules,
)

MONDAY_AFTERNOON = datetime(2024, 1, 15, 16, 30)
MONDAY_EVENING = datetime(2024, 1, 15, 19, 15)
SATURDAY_MORNING = datetime(2024, 1, 20, 10, 0)


class LoopStop(BaseException):
    """Stop the controller after N sleep calls without being swallowed by except Exception."""


def freeze_now(monkeypatch, when):
    monkeypatch.setattr(controller, "_now", lambda: when)


@pytest.fixture(autouse=True)
def skip_block_countdown(monkeypatch):
    monkeypatch.setattr(controller, "show_block_countdown", lambda *args, **kwargs: True)


@pytest.fixture(autouse=True)
def skip_browse_inspect(monkeypatch):
    monkeypatch.setattr(controller.browse, "inspect", lambda: None)


@pytest.fixture(autouse=True)
def skip_status_page(monkeypatch):
    monkeypatch.setattr(controller, "_publish_status_page", lambda *args, **kwargs: None)


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
        mod.inspect = None
        mod.is_active.return_value = is_active
        modules[name] = mod
    monkeypatch.setattr(controller, "MODULES", modules)
    return modules


def test_skips_disabled_and_unknown_resources(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
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
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 0
    assert get_usage(app_dir / "state", "youtube", now=MONDAY_AFTERNOON) == 15
    assert get_usage(app_dir / "state", "youtube", window_id="all_day", now=MONDAY_AFTERNOON) == 15


def test_tracks_aliased_resource_via_module_field(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True, youtube=True)
    write_rules(
        app_dir,
        make_config(
            resources={
                "youtube_shorts": make_resource(enabled=True, module="youtube"),
            }
        ),
    )

    run_cycles(app_dir, monkeypatch)

    modules["youtube"].is_active.assert_called_once()
    assert get_usage(app_dir / "state", "youtube_shorts", now=MONDAY_AFTERNOON) == 15


def test_records_youtube_watch_history_in_sequence(app_dir, monkeypatch, caplog):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    pages = [
        {
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "title": "First",
            "video": {
                "id": "aaaaaaaaaaa",
                "title": "First",
                "channel": "Channel A",
                "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            },
        },
        {
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "title": "First",
            "video": {
                "id": "aaaaaaaaaaa",
                "title": "First",
                "channel": "Channel A",
                "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            },
        },
        {
            "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
            "title": "Second",
            "video": {
                "id": "bbbbbbbbbbb",
                "title": "Second",
                "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
            },
        },
        {
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "title": "First",
            "video": {
                "id": "aaaaaaaaaaa",
                "title": "First",
                "channel": "Channel A",
                "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            },
        },
    ]
    mod = MagicMock()
    mod.inspect.side_effect = pages
    monkeypatch.setattr(controller, "MODULES", {"youtube": mod})
    write_rules(app_dir, make_config(resources={"youtube": make_resource(enabled=True)}))

    import logging

    caplog.set_level(logging.INFO)
    run_cycles(app_dir, monkeypatch, cycles=4)

    state = load_state(app_dir / "state", "youtube", now=MONDAY_AFTERNOON)
    assert [item["id"] for item in state["videos"]] == ["aaaaaaaaaaa", "bbbbbbbbbbb", "aaaaaaaaaaa"]
    assert state["videos"][0]["usage_seconds"] == 30
    assert state["videos"][1]["usage_seconds"] == 15
    assert state["videos"][2]["usage_seconds"] == 15
    watched = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Watched youtube:")]
    assert watched == [
        "Watched youtube: aaaaaaaaaaa First (Channel A)",
        "Watched youtube: bbbbbbbbbbb Second",
        "Watched youtube: aaaaaaaaaaa First (Channel A)",
    ]
    mod.is_active.assert_not_called()


def test_blocked_youtube_still_records_video(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    video = {"id": "abc123defgh", "title": "Blocked clip", "url": "https://www.youtube.com/watch?v=abc123defgh"}
    mod = MagicMock()
    mod.inspect.return_value = {"url": video["url"], "title": video["title"], "video": video}
    monkeypatch.setattr(controller, "MODULES", {"youtube": mod})
    write_rules(
        app_dir,
        make_config(
            resources={"youtube": make_resource(default=make_day_policy(allowed_windows=[]))}
        ),
    )

    run_cycles(app_dir, monkeypatch)

    mod.enforce.assert_called_once()
    state = load_state(app_dir / "state", "youtube", now=MONDAY_AFTERNOON)
    assert state["total_usage_seconds"] == 0
    assert [item["id"] for item in state["videos"]] == ["abc123defgh"]
    assert state["videos"][0]["usage_seconds"] == 0


def test_paused_youtube_does_not_count_usage(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    video = {
        "id": "aaaaaaaaaaa",
        "title": "First",
        "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
    }
    mod = MagicMock()
    mod.inspect.return_value = {
        "url": video["url"],
        "title": video["title"],
        "playback": "paused",
        "video": video,
    }
    monkeypatch.setattr(controller, "MODULES", {"youtube": mod})
    write_rules(app_dir, make_config(resources={"youtube": make_resource(enabled=True)}))

    run_cycles(app_dir, monkeypatch)

    mod.enforce.assert_not_called()
    assert get_usage(app_dir / "state", "youtube", now=MONDAY_AFTERNOON) == 0
    assert load_state(app_dir / "state", "youtube", now=MONDAY_AFTERNOON)["videos"] == []


def test_paused_youtube_still_blocks_when_not_allowed(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    video = {"id": "abc123defgh", "title": "Blocked clip", "url": "https://www.youtube.com/watch?v=abc123defgh"}
    mod = MagicMock()
    mod.inspect.return_value = {
        "url": video["url"],
        "title": video["title"],
        "playback": "paused",
        "video": video,
    }
    monkeypatch.setattr(controller, "MODULES", {"youtube": mod})
    write_rules(
        app_dir,
        make_config(
            resources={"youtube": make_resource(default=make_day_policy(allowed_windows=[]))}
        ),
    )

    run_cycles(app_dir, monkeypatch)

    mod.enforce.assert_called_once()
    assert get_usage(app_dir / "state", "youtube", now=MONDAY_AFTERNOON) == 0


def test_background_roblox_does_not_count_usage(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    mod = MagicMock()
    mod.inspect.return_value = {"foreground": False}
    monkeypatch.setattr(controller, "MODULES", {"roblox": mod})
    write_rules(app_dir, make_config(resources={"roblox": make_resource(enabled=True)}))

    run_cycles(app_dir, monkeypatch)

    mod.enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 0


def test_background_roblox_still_blocks_when_not_allowed(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    mod = MagicMock()
    mod.inspect.return_value = {"foreground": False}
    monkeypatch.setattr(controller, "MODULES", {"roblox": mod})
    write_rules(
        app_dir,
        make_config(
            resources={"roblox": make_resource(default=make_day_policy(allowed_windows=[]))}
        ),
    )

    run_cycles(app_dir, monkeypatch)

    mod.enforce.assert_called_once()
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 0


def test_inactive_resource_is_not_counted_or_blocked(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=False)
    write_rules(app_dir, make_config())

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 0


def test_active_in_window_under_limit_records_usage(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            check_interval_seconds=20,
            resources={"roblox": make_resource(default=make_day_policy(daily_limit_minutes=30))},
        ),
    )

    slept = run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 20
    assert get_usage(app_dir / "state", "roblox", window_id="all_day", now=MONDAY_AFTERNOON) == 20
    assert slept == [20]


def test_active_outside_window_is_blocked_without_usage(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={"roblox": make_resource(default=make_day_policy(allowed_windows=[]))}
        ),
    )

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_called_once()
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 0


def test_block_shows_countdown_then_enforces(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    order = []

    def countdown(title, message, seconds=None):
        order.append(("countdown", title, message))
        return True

    monkeypatch.setattr(controller, "show_block_countdown", countdown)
    modules = install_modules(monkeypatch, roblox=True)
    modules["roblox"].enforce.side_effect = lambda _resource: order.append("enforce")
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    display_name="Roblox",
                    default=make_day_policy(allowed_windows=[]),
                )
            }
        ),
    )

    run_cycles(app_dir, monkeypatch)

    assert order[0] == (
        "countdown",
        "TimeFence",
        "Roblox is not allowed right now.",
    )
    assert order[1] == "enforce"


def test_block_still_enforces_if_countdown_fails(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    monkeypatch.setattr(
        controller,
        "show_block_countdown",
        MagicMock(side_effect=RuntimeError("osascript failed")),
    )
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(resources={"roblox": make_resource(default=make_day_policy(allowed_windows=[]))}),
    )

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_called_once()


def test_active_at_daily_limit_is_blocked(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={"roblox": make_resource(default=make_day_policy(daily_limit_minutes=1))}
        ),
    )
    add_usage(app_dir / "state", "roblox", 60, window_id="all_day", now=MONDAY_AFTERNOON)

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_called_once()
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 60


def test_grant_allows_over_daily_limit(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True)
    resource = make_resource(default=make_day_policy(daily_limit_minutes=1))
    write_rules(app_dir, make_config(resources={"roblox": resource}))
    add_usage(app_dir / "state", "roblox", 60, window_id="all_day", now=MONDAY_AFTERNOON)
    apply_grant(
        app_dir / "state",
        "roblox",
        resolve_policy(resource, now=MONDAY_AFTERNOON),
        15,
        now=MONDAY_AFTERNOON,
    )

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 75


def test_zero_daily_limit_means_no_cap(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={"roblox": make_resource(default=make_day_policy(daily_limit_minutes=0))}
        ),
    )
    add_usage(app_dir / "state", "roblox", 10_000, window_id="all_day", now=MONDAY_AFTERNOON)

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 10_015


def test_weekend_day_policy_is_selected(app_dir, monkeypatch):
    freeze_now(monkeypatch, SATURDAY_MORNING)
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    default=make_day_policy(allowed_windows=[]),
                    days={"saturday": make_day_policy(daily_limit_minutes=90)},
                )
            }
        ),
    )

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox", now=SATURDAY_MORNING) == 15


def test_window_limit_does_not_consume_later_window(app_dir, monkeypatch):
    windows = [
        make_window("after_school", "16:00", "18:00", limit_minutes=1),
        make_window("evening", "19:00", "20:30", limit_minutes=1),
    ]
    resource = make_resource(default=make_day_policy(daily_limit_minutes=45, allowed_windows=windows))
    write_rules(app_dir, make_config(resources={"roblox": resource}))
    add_usage(app_dir / "state", "roblox", 60, window_id="after_school", now=MONDAY_AFTERNOON)

    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    afternoon = install_modules(monkeypatch, roblox=True)
    run_cycles(app_dir, monkeypatch)
    afternoon["roblox"].enforce.assert_called_once()
    assert get_usage(app_dir / "state", "roblox", window_id="evening", now=MONDAY_AFTERNOON) == 0

    freeze_now(monkeypatch, MONDAY_EVENING)
    evening = install_modules(monkeypatch, roblox=True)
    run_cycles(app_dir, monkeypatch)
    evening["roblox"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox", window_id="evening", now=MONDAY_EVENING) == 15
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_EVENING) == 75


def test_daily_limit_blocks_even_when_later_window_has_budget(app_dir, monkeypatch):
    windows = [
        make_window("after_school", "16:00", "18:00", limit_minutes=30),
        make_window("evening", "19:00", "20:30", limit_minutes=30),
    ]
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    default=make_day_policy(daily_limit_minutes=1, allowed_windows=windows)
                )
            }
        ),
    )
    add_usage(app_dir / "state", "roblox", 60, window_id="after_school", now=MONDAY_EVENING)
    freeze_now(monkeypatch, MONDAY_EVENING)
    modules = install_modules(monkeypatch, roblox=True)

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_called_once()
    assert get_usage(app_dir / "state", "roblox", window_id="evening", now=MONDAY_EVENING) == 0


def test_revision_change_is_logged_once(app_dir, monkeypatch, caplog):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    install_modules(monkeypatch, roblox=False)
    write_rules(app_dir, make_config(revision=4))

    import logging

    caplog.set_level(logging.INFO)
    run_cycles(app_dir, monkeypatch, cycles=2)

    messages = [r.getMessage() for r in caplog.records if "Loaded config revision" in r.getMessage()]
    assert messages == ["Loaded config revision 4"]


def test_invalid_config_keeps_last_valid(app_dir, monkeypatch, caplog):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    modules = install_modules(monkeypatch, roblox=True)
    good = make_config(check_interval_seconds=9)
    calls = {"n": 0}

    def flaky_load(_path):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("bad remote config")
        return good

    monkeypatch.setattr(controller, "load_config", flaky_load)
    import logging

    caplog.set_level(logging.ERROR)
    slept = run_cycles(app_dir, monkeypatch, cycles=2)

    assert slept == [9, 9]
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 18
    modules["roblox"].enforce.assert_not_called()
    assert any("Invalid config; keeping last valid configuration" in r.getMessage() for r in caplog.records)


def test_cycle_failure_uses_default_interval_then_continues(app_dir, monkeypatch, caplog):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
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
    assert any("Invalid config; keeping last valid configuration" in r.getMessage() for r in caplog.records)


def test_one_resource_failure_does_not_skip_remaining_resources(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
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

    modules["youtube"].is_active.assert_called_once()
    assert get_usage(app_dir / "state", "youtube", now=MONDAY_AFTERNOON) == 15


def test_daily_warning_fires_once_when_threshold_crossed(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    notify = MagicMock(return_value=True)
    monkeypatch.setattr(controller, "show_notification", notify)
    install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    display_name="Roblox",
                    default=make_day_policy(daily_limit_minutes=45, warning_minutes=[10, 5, 1]),
                )
            }
        ),
    )
    add_usage(app_dir / "state", "roblox", 45 * 60 - 10 * 60 - 8, window_id="all_day", now=MONDAY_AFTERNOON)

    run_cycles(app_dir, monkeypatch, cycles=2)

    messages = [call.args[1] for call in notify.call_args_list]
    assert messages == ["Roblox has 10 minutes remaining today."]
    assert notify.call_args.args[0] == "TimeFence"
    state = load_state(app_dir / "state", "roblox", now=MONDAY_AFTERNOON)
    assert state["warnings_sent"] == ["daily:10"]


def test_daily_and_window_warning_share_one_dialog(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    notify = MagicMock(return_value=True)
    monkeypatch.setattr(controller, "show_notification", notify)
    install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    display_name="Roblox",
                    default=make_day_policy(
                        daily_limit_minutes=3,
                        warning_minutes=[2, 1],
                        allowed_windows=[
                            make_window(
                                "evening",
                                "00:00",
                                "24:00",
                                limit_minutes=3,
                                warning_minutes=[2, 1],
                            )
                        ],
                    ),
                )
            }
        ),
    )
    add_usage(app_dir / "state", "roblox", 60, window_id="evening", now=MONDAY_AFTERNOON)

    run_cycles(app_dir, monkeypatch)

    assert notify.call_count == 1
    assert notify.call_args.args[1] == (
        "Roblox has 2 minutes remaining today, including the evening window."
    )
    state = load_state(app_dir / "state", "roblox", now=MONDAY_AFTERNOON)
    assert "daily:2" in state["warnings_sent"]
    assert "2" in state["windows"]["evening"]["warnings_sent"]


def test_notification_failure_does_not_affect_enforcement(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    monkeypatch.setattr(controller, "show_notification", MagicMock(side_effect=RuntimeError("osascript failed")))
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    default=make_day_policy(daily_limit_minutes=45, warning_minutes=[10, 5, 1])
                )
            }
        ),
    )
    add_usage(app_dir / "state", "roblox", 45 * 60, window_id="all_day", now=MONDAY_AFTERNOON)

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_called_once()
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 45 * 60


def test_notification_failure_still_records_usage(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    monkeypatch.setattr(controller, "show_notification", MagicMock(side_effect=RuntimeError("osascript failed")))
    modules = install_modules(monkeypatch, roblox=True)
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    default=make_day_policy(daily_limit_minutes=45, warning_minutes=[10, 5, 1])
                )
            }
        ),
    )
    add_usage(app_dir / "state", "roblox", 45 * 60 - 10 * 60 - 8, window_id="all_day", now=MONDAY_AFTERNOON)

    run_cycles(app_dir, monkeypatch)

    modules["roblox"].enforce.assert_not_called()
    assert get_usage(app_dir / "state", "roblox", now=MONDAY_AFTERNOON) == 45 * 60 - 10 * 60 - 8 + 15
    assert load_state(app_dir / "state", "roblox", now=MONDAY_AFTERNOON)["warnings_sent"] == []


def test_browse_log_records_front_tab(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    install_modules(monkeypatch, roblox=False)
    monkeypatch.setattr(
        controller.browse,
        "inspect",
        lambda: {
            "host": "www.example.com",
            "url": "https://www.example.com/page",
            "title": "Example",
        },
    )
    write_rules(app_dir, make_config(log_browsing=True))

    run_cycles(app_dir, monkeypatch)

    from timefence.browse import load_browse_state

    state = load_browse_state(app_dir / "state", now=MONDAY_AFTERNOON)
    assert state["visits"][0]["host"] == "www.example.com"
    assert state["visits"][0]["usage_seconds"] == 15
    assert (app_dir / "state" / "browse" / "2024-01-15.txt").exists()


def test_browse_log_can_be_disabled(app_dir, monkeypatch):
    freeze_now(monkeypatch, MONDAY_AFTERNOON)
    install_modules(monkeypatch, roblox=False)
    inspect = MagicMock(return_value={"host": "www.example.com", "url": "https://www.example.com/", "title": "X"})
    monkeypatch.setattr(controller.browse, "inspect", inspect)
    write_rules(app_dir, make_config(log_browsing=False))

    run_cycles(app_dir, monkeypatch)

    inspect.assert_not_called()
    assert not (app_dir / "state" / "browse").exists()


def test_screen_time_counts_elapsed_for_bundle_app(app_dir, monkeypatch):
    from timefence.models.activity import FrontmostApp, Observation

    times = [
        datetime(2024, 1, 15, 16, 30, 0),
        datetime(2024, 1, 15, 16, 30, 10),
    ]
    idx = {"n": 0}

    def now():
        return times[min(idx["n"], len(times) - 1)]

    monkeypatch.setattr(controller, "_now", now)
    monkeypatch.setattr(
        controller.MacOSActivityMonitor,
        "capture",
        lambda self, now=None: Observation(
            timestamp=now,
            idle_seconds=0,
            screen_locked=False,
            frontmost=FrontmostApp("Roblox", "com.roblox.RobloxPlayer", 99),
        ),
    )
    modules = install_modules(monkeypatch, roblox=True)
    modules["roblox"].inspect = MagicMock(return_value={"foreground": True})
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    enabled=True,
                    type="app",
                    bundle_ids=["com.roblox.RobloxPlayer"],
                )
            }
        ),
    )

    slept, sleep = stop_after(2)

    def sleep_and_advance(seconds):
        idx["n"] += 1
        return sleep(seconds)

    monkeypatch.setattr(controller.time, "sleep", sleep_and_advance)
    with pytest.raises(LoopStop):
        controller.run(app_dir)

    assert get_usage(app_dir / "state", "roblox", now=times[1]) == 10
    modules["roblox"].enforce.assert_not_called()
