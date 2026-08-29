from datetime import datetime

from timefence.budget import (
    format_clock,
    format_summary,
    format_time_of_day,
    remaining_seconds,
    resource_budget,
    summarize,
)
from timefence.usage import add_usage
from tests.helpers import make_config, make_day_policy, make_resource, make_window, write_rules

MONDAY_AFTERNOON = datetime(2024, 1, 15, 16, 30)


def test_format_clock_and_remaining():
    assert format_clock(0) == "0 seconds"
    assert format_clock(45) == "45 seconds"
    assert format_clock(75) == "1 minute and 15 seconds"
    assert format_clock(3600) == "1 hour"
    assert format_clock(3723) == "1 hour and 2 minutes"
    assert remaining_seconds(0, 10) is None
    assert remaining_seconds(60, 10) == 50
    assert remaining_seconds(60, 90) == 0
    assert format_time_of_day("16:00") == "4:00 PM"
    assert format_time_of_day("09:05") == "9:05 AM"


def test_resource_budget_daily_and_current_window(app_dir):
    resource = make_resource(
        display_name="Roblox",
        default=make_day_policy(
            daily_limit_minutes=45,
            allowed_windows=[
                make_window("after_school", "16:00", "18:00", limit_minutes=30),
                make_window("evening", "19:00", "20:30", limit_minutes=30),
            ],
        ),
    )
    add_usage(app_dir / "state", "roblox", 12 * 60, window_id="after_school", now=MONDAY_AFTERNOON)
    row = resource_budget(
        "roblox",
        resource,
        {"total_usage_seconds": 12 * 60, "windows": {"after_school": {"usage_seconds": 12 * 60}}},
        MONDAY_AFTERNOON,
    )
    assert row["label"] == "Roblox"
    assert row["allowed"] is True
    assert "after school" in row["now"]
    assert row["daily_used"] == 12 * 60
    assert row["daily_limit"] == 45 * 60
    assert row["daily_remaining"] == 33 * 60
    assert row["windows"][0]["current"] is True
    assert row["windows"][0]["remaining"] == 18 * 60
    assert row["windows"][1]["current"] is False
    assert row["windows"][1]["remaining"] == 30 * 60


def test_summarize_skips_disabled_and_formats_text(app_dir):
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    display_name="Roblox",
                    default=make_day_policy(daily_limit_minutes=45),
                ),
                "youtube": make_resource(enabled=False, default=make_day_policy()),
            }
        ),
    )
    add_usage(app_dir / "state", "roblox", 600, window_id="all_day", now=MONDAY_AFTERNOON)
    text = format_summary(
        summarize(
            make_config(
                resources={
                    "roblox": make_resource(
                        display_name="Roblox",
                        default=make_day_policy(daily_limit_minutes=45),
                    ),
                    "youtube": make_resource(enabled=False),
                }
            ),
            app_dir / "state",
            now=MONDAY_AFTERNOON,
        ),
        now=MONDAY_AFTERNOON,
    )
    assert "Here is the TimeFence budget for Monday, January 15, 2024 at 4:30 PM." in text
    assert "Roblox is allowed right now during the all day window." in text
    assert "Today Roblox has used 10 minutes of 45 minutes allowed, with 35 minutes remaining." in text
    assert "This is the current window." in text
    assert "youtube" not in text.lower()
