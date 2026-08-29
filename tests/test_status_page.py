from datetime import datetime
from urllib.request import urlopen

from timefence import browse
from timefence.status_page import page_model, render_html, write_html
from timefence.status_server import ensure, stop, url
from timefence.usage import add_usage
from tests.helpers import make_config, make_day_policy, make_resource, make_window, write_rules

MONDAY_AFTERNOON = datetime(2024, 1, 15, 16, 30)


def _rules(app_dir):
    write_rules(
        app_dir,
        make_config(
            resources={
                "roblox": make_resource(
                    display_name="Roblox",
                    default=make_day_policy(
                        daily_limit_minutes=45,
                        allowed_windows=[
                            make_window("after_school", "16:00", "18:00", limit_minutes=30)
                        ],
                    ),
                )
            }
        ),
    )
    add_usage(app_dir / "state", "roblox", 12 * 60, window_id="after_school", now=MONDAY_AFTERNOON)


def test_page_model_remaining(app_dir):
    _rules(app_dir)
    model = page_model(
        make_config(
            resources={
                "roblox": make_resource(
                    display_name="Roblox",
                    default=make_day_policy(
                        daily_limit_minutes=45,
                        allowed_windows=[
                            make_window("after_school", "16:00", "18:00", limit_minutes=30)
                        ],
                    ),
                )
            }
        ),
        app_dir / "state",
        now=MONDAY_AFTERNOON,
    )
    row = model["resources"][0]
    assert row["label"] == "Roblox"
    assert row["kind"] == "ok"
    assert row["daily_remaining_label"] == "33 minutes"
    assert row["percent"] == 27
    assert "OK to use now" in row["status_short"]
    assert row["windows"][0]["current"] is True
    assert model["show_sites"] is True
    assert model["sites"] == []


def test_render_html_escapes_and_shows_remaining(app_dir):
    resource = make_resource(
        display_name='YouTube <script>alert("x")</script>',
        default=make_day_policy(daily_limit_minutes=10),
    )
    model = page_model(
        make_config(resources={"youtube": resource}),
        app_dir / "state",
        now=MONDAY_AFTERNOON,
    )
    page = render_html(model)
    assert "Your time today" in page
    assert "<script>alert" not in page
    assert "YouTube &lt;script&gt;" in page
    assert "10 minutes left today" in page or "10 minutes" in page
    assert 'http-equiv="refresh"' in page


def test_write_html(app_dir):
    _rules(app_dir)
    path = write_html(
        app_dir,
        now=MONDAY_AFTERNOON,
        cfg=make_config(
            resources={
                "roblox": make_resource(
                    display_name="Roblox",
                    default=make_day_policy(daily_limit_minutes=45),
                )
            }
        ),
    )
    text = path.read_text(encoding="utf-8")
    assert path.name == "status.html"
    assert "Roblox" in text
    assert "left today" in text


def test_page_includes_top_websites(app_dir):
    _rules(app_dir)
    t0 = MONDAY_AFTERNOON
    browse.note_visit(
        app_dir / "state",
        {
            "host": "www.google.com",
            "url": "https://www.google.com/search?q=cats",
            "title": "<Cats>",
        },
        90,
        now=t0,
    )
    browse.note_visit(
        app_dir / "state",
        {"host": "news.ycombinator.com", "url": "https://news.ycombinator.com/", "title": "HN"},
        30,
        now=t0,
    )
    cfg = make_config(
        resources={
            "roblox": make_resource(
                display_name="Roblox",
                default=make_day_policy(daily_limit_minutes=45),
            )
        }
    )
    model = page_model(cfg, app_dir / "state", now=t0)
    assert [item["host"] for item in model["sites"]] == ["google.com", "news.ycombinator.com"]
    assert model["sites"][0]["percent"] == 100
    page = render_html(model)
    assert "Top websites today" in page
    assert "google.com" in page
    assert "<Cats>" not in page
    assert "1 minute and 30 seconds" in page


def test_http_server_serves_live_page(app_dir):
    _rules(app_dir)
    httpd, port = ensure(app_dir, 0)
    try:
        assert port >= 1
        with urlopen(url(port), timeout=2) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert "Your time today" in body
            assert "Roblox" in body
    finally:
        stop()
