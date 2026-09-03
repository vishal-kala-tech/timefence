import json
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import pytest

from timefence import parent_auth
from timefence.config import load_config
from timefence.identity import RESOURCE_TYPE_APP, RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_VIDEOS_RESOURCE_ID
from timefence.parent_editor import apply_editor, editor_from_config
from timefence.parent_page import render as render_parent
from timefence.status_server import ensure, setup_url, stop, url
from tests.helpers import make_config, make_day_policy, make_resource, make_window, write_rules

SHIPPED = Path(__file__).resolve().parents[1] / "config" / "rules.json"


def test_set_pin_rejects_short_and_unlocks(app_dir):
    with pytest.raises(ValueError, match="at least 4"):
        parent_auth.set_pin(app_dir, "12")
    token = parent_auth.set_pin(app_dir, "2468")
    assert parent_auth.has_pin(app_dir)
    assert parent_auth.valid_token(app_dir, token)
    assert not parent_auth.valid_token(app_dir, "nope")
    with pytest.raises(ValueError, match="Wrong PIN"):
        parent_auth.unlock(app_dir, "0000")
    assert parent_auth.unlock(app_dir, "2468") == token


def _by_key(cfg):
    return {(item["resource_type"], item["resource_id"]): item for item in cfg["resources"]}


def test_editor_round_trip_preserves_filters_and_overrides(app_dir):
    cfg = make_config(
        revision=4,
        log_browsing=True,
        resources=[
            make_resource(
                resource_type=RESOURCE_TYPE_VIDEO_CATEGORY,
                resource_id=YOUTUBE_VIDEOS_RESOURCE_ID,
                display_name="YouTube",
                url_contains=["youtube.com/watch"],
                url_excludes=["youtube.com/shorts"],
                module="youtube",
                date_overrides={"2026-12-25": make_day_policy(daily_limit_minutes=0)},
                default=make_day_policy(
                    daily_limit_minutes=30,
                    warning_minutes=[10, 5],
                    allowed_windows=[make_window("evening", "17:00", "19:00", limit_minutes=30)],
                ),
                days={"monday": make_day_policy(daily_limit_minutes=10)},
            )
        ],
    )
    editor = editor_from_config(cfg)
    editor["log_browsing"] = False
    editor["resources"][0]["display_name"] = "YT"
    editor["resources"][0]["default"]["daily_limit_minutes"] = 20
    editor["resources"][0]["saturday"] = {
        "daily_limit_minutes": 40,
        "warning_minutes": "10, 5",
        "windows": [{"name": "morning", "start": "10:00", "end": "12:00", "limit_minutes": 20}],
    }
    saved = apply_editor(cfg, editor)
    youtube = _by_key(saved)[(RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_VIDEOS_RESOURCE_ID)]
    assert saved["revision"] == 5
    assert saved["log_browsing"] is False
    assert youtube["display_name"] == "YT"
    assert youtube["url_contains"] == ["youtube.com/watch"]
    assert youtube["url_excludes"] == ["youtube.com/shorts"]
    assert youtube["resource_type"] == RESOURCE_TYPE_VIDEO_CATEGORY
    assert youtube["resource_id"] == YOUTUBE_VIDEOS_RESOURCE_ID
    assert youtube["policy"]["date_overrides"]["2026-12-25"]["daily_limit_minutes"] == 0
    assert youtube["policy"]["days"]["monday"]["daily_limit_minutes"] == 10
    assert youtube["policy"]["days"]["saturday"]["allowed_windows"][0]["id"] == "morning"
    assert youtube["policy"]["default"]["daily_limit_minutes"] == 20


def test_editor_round_trip_shipped_rules():
    cfg = load_config(SHIPPED)
    again = apply_editor(cfg, editor_from_config(cfg))
    youtube = _by_key(again)[(RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_VIDEOS_RESOURCE_ID)]
    original = _by_key(cfg)[(RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_VIDEOS_RESOURCE_ID)]
    assert youtube["url_contains"] == original["url_contains"]
    assert youtube["url_excludes"] == original["url_excludes"]
    assert again["revision"] == cfg["revision"] + 1
    assert _by_key(again)[(RESOURCE_TYPE_APP, "com.roblox.Roblox")]["policy"]["days"]["saturday"][
        "daily_limit_minutes"
    ] == 120


def test_parent_html_has_grant_and_rules_forms():
    page = render_parent()
    assert "Grant extra time" in page
    assert "Standing rules" in page
    assert 'id="grant-form"' in page
    assert 'id="rules-form"' in page
    assert 'id="panel-activity"' in page
    assert 'id="panel-resources"' in page
    assert 'id="tab-resources"' in page
    assert 'id="resource-add-form"' in page
    assert "/api/parent/resources" in page
    assert 'id="lock"' in page
    assert "Apps" in page
    assert "Websites" in page
    assert "Limits today" in page
    assert "/api/parent/activity" in page
    assert "parent PIN" in page
    assert "App names" not in page
    assert 'id="panel-names"' not in page
    assert "/api/parent/app-names" not in page


def _opener():
    return build_opener(HTTPCookieProcessor(CookieJar()))


def _json(opener, target, method="GET", data=None):
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(target, data=body, headers=headers, method=method)
    try:
        with opener.open(req, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        return exc.code, payload


def test_parent_http_pin_rules_and_grant(app_dir):
    write_rules(
        app_dir,
        make_config(
            resources=[
                make_resource(
                    resource_type=RESOURCE_TYPE_VIDEO_CATEGORY,
                    resource_id=YOUTUBE_VIDEOS_RESOURCE_ID,
                    display_name="YouTube",
                    default=make_day_policy(
                        daily_limit_minutes=30,
                        allowed_windows=[make_window("evening", "17:00", "19:00", limit_minutes=30)],
                    ),
                )
            ]
        ),
    )
    httpd, port = ensure(app_dir, 0)
    try:
        base = url(port).rstrip("/")
        with urlopen(base + "/", timeout=2) as response:
            kid = response.read().decode("utf-8")
        assert "Your time today" in kid
        assert "Grant extra time" not in kid
        assert "/setup" not in kid
        assert 'id="grant-form"' not in kid
        assert "parent PIN" not in kid

        with urlopen(base + "/setup", timeout=2) as response:
            setup = response.read().decode("utf-8")
        assert "Grant extra time" in setup
        assert "Standing rules" in setup

        anon = _opener()
        code, payload = _json(anon, base + "/api/rules")
        assert code == 401
        code, payload = _json(anon, base + "/api/parent/session")
        assert code == 200
        assert payload == {"has_pin": False, "unlocked": False}

        code, payload = _json(anon, base + "/api/pin", "POST", {"pin": "12"})
        assert code == 400

        code, payload = _json(anon, base + "/api/pin", "POST", {"pin": "2468"})
        assert code == 200
        assert payload["unlocked"] is True

        code, editor = _json(anon, base + "/api/rules")
        assert code == 200
        assert editor["resources"][0]["resource_type"] == RESOURCE_TYPE_VIDEO_CATEGORY
        assert editor["resources"][0]["resource_id"] == YOUTUBE_VIDEOS_RESOURCE_ID
        editor["resources"][0]["default"]["daily_limit_minutes"] = 25
        code, saved = _json(anon, base + "/api/rules", "PUT", editor)
        assert code == 200
        assert saved["resources"][0]["default"]["daily_limit_minutes"] == 25
        live = load_config(app_dir / "config/rules.json")
        youtube = _by_key(live)[(RESOURCE_TYPE_VIDEO_CATEGORY, YOUTUBE_VIDEOS_RESOURCE_ID)]
        assert youtube["policy"]["default"]["daily_limit_minutes"] == 25

        code, managed = _json(anon, base + "/api/parent/resources")
        assert code == 200
        assert managed["resources"][0]["resource_id"] == YOUTUBE_VIDEOS_RESOURCE_ID
        assert managed["resources"][0]["listed"] is True

        code, managed = _json(
            anon,
            base + "/api/parent/resources",
            "POST",
            {
                "resource_type": RESOURCE_TYPE_APP,
                "resource_id": "com.apple.Terminal",
                "display_name": "Mac Terminal",
            },
        )
        assert code == 200
        terminal = next(row for row in managed["resources"] if row["resource_id"] == "com.apple.Terminal")
        assert terminal["display_name"] == "Mac Terminal"
        assert terminal["listed"] is True

        code, managed = _json(
            anon,
            base + "/api/parent/resources/app/com.apple.Terminal",
            "PUT",
            {"display_name": "Terminal"},
        )
        assert code == 200
        terminal = next(row for row in managed["resources"] if row["resource_id"] == "com.apple.Terminal")
        assert terminal["display_name"] == "Terminal"

        code, managed = _json(anon, base + "/api/parent/resources/app/com.apple.Terminal", "DELETE")
        assert code == 200
        assert all(row["resource_id"] != "com.apple.Terminal" or not row["listed"] for row in managed["resources"])
        live = load_config(app_dir / "config/rules.json")
        assert all(item["resource_id"] != "com.apple.Terminal" for item in live["resources"])

        other = _opener()
        code, payload = _json(other, base + "/api/pin", "POST", {"pin": "0000"})
        assert code == 403
        code, payload = _json(other, base + "/api/grants")
        assert code == 401

        code, granted = _json(
            anon,
            base + "/api/grants",
            "POST",
            {
                "resource_type": RESOURCE_TYPE_VIDEO_CATEGORY,
                "resource_id": YOUTUBE_VIDEOS_RESOURCE_ID,
                "minutes": 15,
            },
        )
        assert code == 200
        assert granted["grants"][0]["resource_type"] == RESOURCE_TYPE_VIDEO_CATEGORY
        assert granted["grants"][0]["resource_id"] == YOUTUBE_VIDEOS_RESOURCE_ID
        assert granted["grants"][0]["display_name"] == "YouTube"
        assert "Bonus until" in granted["grants"][0]["summary"]

        code, cleared = _json(
            anon,
            base + f"/api/grants/{RESOURCE_TYPE_VIDEO_CATEGORY}/{YOUTUBE_VIDEOS_RESOURCE_ID}",
            "DELETE",
        )
        assert code == 200
        assert cleared["grants"] == []

        code, payload = _json(anon, base + "/api/logout", "POST", {})
        assert code == 200
        code, payload = _json(anon, base + "/api/rules")
        assert code == 401
    finally:
        stop()


def test_setup_url():
    assert setup_url(8743) == "http://127.0.0.1:8743/setup"
