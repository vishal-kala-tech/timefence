#!/usr/bin/env python3
"""Seed the last 30 days of activity into the live TimeFence state.

Skips dates that already have daily totals so today's real usage is kept.
Does not change rules, grants, or PIN. Re-run is a no-op for seeded days.
"""

from __future__ import annotations

import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from timefence import browse
from timefence.identity import (
    RESOURCE_TYPE_APP,
    default_display_name,
    ensure_resource,
)
from timefence.tracking.sqlite_usage_store import SqliteUsageStore
from timefence.usage import add_usage

APP = Path(os.environ.get("TIME_FENCE_HOME", Path.home() / "Library/Application Support/TimeFence"))
STATE = APP / "state"

SITES = [
    ("github.com", "GitHub", "https://github.com/"),
    ("classroom.google.com", "Google Classroom", "https://classroom.google.com/"),
    ("docs.google.com", "Google Docs", "https://docs.google.com/document/d/seed"),
    ("mail.google.com", "Gmail", "https://mail.google.com/"),
    ("khanacademy.org", "Khan Academy", "https://www.khanacademy.org/"),
    ("wikipedia.org", "Wikipedia", "https://en.wikipedia.org/wiki/Main_Page"),
    ("stackoverflow.com", "Stack Overflow", "https://stackoverflow.com/"),
    ("chatgpt.com", "ChatGPT", "https://chatgpt.com/"),
    ("youtube.com", "YouTube", "https://www.youtube.com/"),
    ("roblox.com", "Roblox", "https://www.roblox.com/home"),
    ("twitch.tv", "Twitch", "https://www.twitch.tv/"),
    ("reddit.com", "Reddit", "https://www.reddit.com/"),
]

VIDEOS = [
    ("vid01", "Speedrun world record", "SpeedClips", "https://www.youtube.com/watch?v=aaaaaaaaaa1"),
    ("vid02", "Homework help: fractions", "Khan Academy", "https://www.youtube.com/watch?v=aaaaaaaaaa2"),
    ("vid03", "Minecraft build tour", "BlockCraft", "https://www.youtube.com/watch?v=aaaaaaaaaa3"),
    ("vid04", "Funny cat compilation", "PetsDaily", "https://www.youtube.com/watch?v=aaaaaaaaaa4"),
    ("vid05", "How circuits work", "ScienceClick", "https://www.youtube.com/watch?v=aaaaaaaaaa5"),
    ("vid06", "Roblox tycoon episode 12", "GameNight", "https://www.youtube.com/watch?v=aaaaaaaaaa6"),
    ("vid07", "Piano lesson 4", "PracticeRoom", "https://www.youtube.com/watch?v=aaaaaaaaaa7"),
    ("vid08", "Space documentary clip", "NightSky", "https://www.youtube.com/watch?v=aaaaaaaaaa8"),
]

SHORTS = [
    ("sh01", "Trick shot", "ClipFarm", "https://www.youtube.com/shorts/bbbbbbbbb1"),
    ("sh02", "Dance trend", "ForYou", "https://www.youtube.com/shorts/bbbbbbbbb2"),
    ("sh03", "Science in 20s", "TinyLab", "https://www.youtube.com/shorts/bbbbbbbbb3"),
]


def at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    extra_hours, minute = divmod(int(minute), 60)
    hour = int(hour) + extra_hours
    extra_days, hour = divmod(hour, 24)
    stamp = datetime(day.year, day.month, day.day, hour, minute, second)
    return stamp + timedelta(days=extra_days)


def jitter(rng: random.Random, seconds: int, spread: float = 0.25) -> int:
    delta = int(seconds * spread)
    return max(45, seconds + rng.randint(-delta, delta))


def closed_session(store: SqliteUsageStore, resource_id: str, start: datetime, seconds: int, identifier: str, resource_type: str = RESOURCE_TYPE_APP) -> None:
    seconds = max(30, int(seconds))
    end = start + timedelta(seconds=seconds)
    stamp = start.isoformat()
    sid = store.start_session(resource_type, resource_id, stamp, identifier=identifier, created_at=stamp)
    store.end_session(sid, end.isoformat(), seconds)
    store.add_active_seconds(start.date().isoformat(), resource_type, resource_id, seconds, end.isoformat())
    ensure_resource(store, resource_type, resource_id, display_name=default_display_name(resource_type, resource_id), now=start)


def seed_day(store: SqliteUsageStore, day: date, rng: random.Random) -> None:
    weekday = day.weekday()  # Mon=0
    weekend = weekday >= 5

    if weekend:
        if rng.random() < 0.12:
            return
        closed_session(store, "com.google.Chrome", at(day, 10, rng.randint(5, 40)), jitter(rng, 22 * 60), "com.google.Chrome")
        if rng.random() < 0.45:
            closed_session(store, "com.todesktop.230313mzl4w4u92", at(day, 11, rng.randint(0, 30)), jitter(rng, 18 * 60), "com.todesktop.230313mzl4w4u92")
        roblox_blocks = [
            (9, 20, "morning", 38 * 60),
            (14, 10, "afternoon", 32 * 60),
            (19, 5, "evening", 18 * 60),
        ]
        if rng.random() < 0.2:
            roblox_blocks = roblox_blocks[:2]
        for hour, minute, window, secs in roblox_blocks:
            start = at(day, hour, minute + rng.randint(0, 12))
            seconds = jitter(rng, secs)
            closed_session(store, "com.roblox.Roblox", start, seconds, "com.roblox.RobloxPlayer")
            add_usage(STATE, "app", "com.roblox.Roblox", seconds, window_id=window, now=start, credit_daily=False)
        yt_count = rng.randint(2, 4)
        for i in range(yt_count):
            video = VIDEOS[(day.toordinal() + i) % len(VIDEOS)]
            start = at(day, 16 + i, rng.randint(0, 40))
            seconds = jitter(rng, rng.randint(8, 16) * 60)
            add_usage(
                STATE,
                "video_category",
                "youtube_videos",
                seconds,
                now=start,
                video={"id": video[0] + day.strftime("%m%d"), "title": video[1], "channel": video[2], "url": video[3]},
            )
        if rng.random() < 0.7:
            short = SHORTS[day.toordinal() % len(SHORTS)]
            start = at(day, 20, rng.randint(0, 25))
            seconds = jitter(rng, rng.randint(4, 9) * 60)
            add_usage(
                STATE,
                "video_category",
                "youtube_shorts",
                seconds,
                now=start,
                video={"id": short[0] + day.strftime("%m%d"), "title": short[1], "channel": short[2], "url": short[3]},
            )
        hosts = rng.sample(SITES, k=rng.randint(4, 7))
        minute = 10
        for host, title, url in hosts:
            start = at(day, 10, minute)
            browse.note_visit(
                STATE,
                {"host": host, "url": url, "title": title, "browser": "chrome"},
                jitter(rng, rng.randint(3, 14) * 60),
                now=start,
            )
            minute += rng.randint(8, 18)
        return

    # School day. Occasional light day.
    light = rng.random() < 0.1
    closed_session(store, "com.todesktop.230313mzl4w4u92", at(day, 8, rng.randint(5, 25)), jitter(rng, (25 if light else 55) * 60), "com.todesktop.230313mzl4w4u92")
    closed_session(store, "com.google.Chrome", at(day, 10, rng.randint(0, 20)), jitter(rng, (12 if light else 28) * 60), "com.google.Chrome")
    if not light and rng.random() < 0.55:
        closed_session(store, "com.microsoft.VSCode", at(day, 13, rng.randint(0, 15)), jitter(rng, 22 * 60), "com.microsoft.VSCode")
    if not light and rng.random() < 0.25:
        closed_session(store, "com.jetbrains.pycharm", at(day, 14, rng.randint(0, 20)), jitter(rng, 16 * 60), "com.jetbrains.pycharm")
    closed_session(store, "com.google.Chrome", at(day, 15, rng.randint(0, 15)), jitter(rng, 12 * 60), "com.google.Chrome")

    if not light:
        start = at(day, 16, rng.randint(5, 20))
        seconds = jitter(rng, rng.randint(16, 28) * 60)
        closed_session(store, "com.roblox.Roblox", start, seconds, "com.roblox.RobloxPlayer")
        add_usage(STATE, "app", "com.roblox.Roblox", seconds, window_id="after_school", now=start, credit_daily=False)
        if rng.random() < 0.45:
            start = at(day, 19, rng.randint(0, 15))
            seconds = jitter(rng, rng.randint(8, 18) * 60)
            closed_session(store, "com.roblox.Roblox", start, seconds, "com.roblox.RobloxPlayer")
            add_usage(STATE, "app", "com.roblox.Roblox", seconds, window_id="evening", now=start, credit_daily=False)

        video = VIDEOS[day.toordinal() % len(VIDEOS)]
        start = at(day, 19, rng.randint(25, 50))
        seconds = jitter(rng, rng.randint(7, 18) * 60)
        add_usage(
            STATE,
            "video_category",
            "youtube_videos",
            seconds,
            now=start,
            video={"id": video[0] + day.strftime("%m%d"), "title": video[1], "channel": video[2], "url": video[3]},
        )
        if rng.random() < 0.4:
            short = SHORTS[(day.toordinal() + 1) % len(SHORTS)]
            start = at(day, 20, rng.randint(10, 40))
            seconds = jitter(rng, rng.randint(3, 8) * 60)
            add_usage(
                STATE,
                "video_category",
                "youtube_shorts",
                seconds,
                now=start,
                video={"id": short[0] + day.strftime("%m%d"), "title": short[1], "channel": short[2], "url": short[3]},
            )

    school_sites = [SITES[i] for i in (0, 1, 2, 3, 4, 6, 7)]
    hosts = rng.sample(school_sites, k=rng.randint(3, 6))
    minute = 8
    for host, title, url in hosts:
        start = at(day, 10, minute)
        browse.note_visit(
            STATE,
            {"host": host, "url": url, "title": title, "browser": "chrome"},
            jitter(rng, rng.randint(2, 11) * 60),
            now=start,
        )
        minute += rng.randint(6, 16)


def main() -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    store = SqliteUsageStore(STATE / "screen_time.sqlite")
    today = date.today()
    start = today - timedelta(days=30)
    skipped = []
    seeded = []
    rng = random.Random(20260902)
    day = start
    while day <= today:
        if store.get_all_daily(day.isoformat()):
            skipped.append(day.isoformat())
        else:
            seed_day(store, day, random.Random(rng.randint(1, 10_000_000)))
            seeded.append(day.isoformat())
        day += timedelta(days=1)
    print("APP", APP)
    print("seeded", len(seeded), "days")
    if seeded:
        print("from", seeded[0], "to", seeded[-1])
    if skipped:
        print("skipped (already had totals)", ", ".join(skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
