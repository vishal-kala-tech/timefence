from unittest.mock import MagicMock

from timefence import browse


def test_parse_page_keeps_host_and_http_urls():
    page = browse.parse_page("https://www.roblox.com/games/123?x=1#frag", "Adopt Me!")
    assert page == {
        "host": "www.roblox.com",
        "url": "https://www.roblox.com/games/123?x=1",
        "title": "Adopt Me!",
    }


def test_parse_page_skips_blank_and_non_http():
    assert browse.parse_page("") is None
    assert browse.parse_page("chrome://newtab/") is None
    assert browse.parse_page("about:blank") is None
    assert browse.parse_page("missing value") is None


def test_inspect_returns_front_tab(monkeypatch):
    monkeypatch.setattr(
        browse.subprocess,
        "run",
        MagicMock(
            return_value=MagicMock(
                stdout="https://www.google.com/search?q=cats\nGoogle\n"
            )
        ),
    )
    page = browse.inspect()
    assert page["host"] == "www.google.com"
    assert page["url"] == "https://www.google.com/search?q=cats"
    assert page["title"] == "Google"


def test_inspect_empty_is_none(monkeypatch):
    monkeypatch.setattr(browse.subprocess, "run", MagicMock(return_value=MagicMock(stdout="")))
    assert browse.inspect() is None


def test_note_visit_collapses_consecutive_same_url(tmp_path):
    from datetime import datetime

    a = {"host": "www.example.com", "url": "https://www.example.com/", "title": "Example"}
    b = {"host": "news.ycombinator.com", "url": "https://news.ycombinator.com/", "title": "HN"}
    t0 = datetime(2024, 1, 15, 16, 30, 0)
    t1 = datetime(2024, 1, 15, 16, 30, 15)
    t2 = datetime(2024, 1, 15, 16, 30, 30)

    browse.note_visit(tmp_path, a, 15, now=t0)
    browse.note_visit(tmp_path, a, 15, now=t1)
    browse.note_visit(tmp_path, b, 15, now=t2)

    state = browse.load_browse_state(tmp_path, now=t0)
    assert [item["url"] for item in state["visits"]] == [
        "https://www.example.com/",
        "https://news.ycombinator.com/",
    ]
    assert state["visits"][0]["usage_seconds"] == 30
    assert state["visits"][0]["last_seen"] == "16:30:15"

    text = browse.browse_table_path(tmp_path, now=t0).read_text(encoding="utf-8")
    assert text.splitlines()[0] == "date|host|url|title|first_seen|last_seen|seconds"
    assert "www.example.com" in text
    assert "news.ycombinator.com" in text


def test_top_sites_ranks_by_time_and_merges_www(tmp_path):
    from datetime import datetime

    t0 = datetime(2024, 1, 15, 16, 30, 0)
    browse.note_visit(
        tmp_path,
        {"host": "www.google.com", "url": "https://www.google.com/search?q=a", "title": "a"},
        15,
        now=t0,
    )
    browse.note_visit(
        tmp_path,
        {"host": "google.com", "url": "https://google.com/", "title": "Google"},
        45,
        now=datetime(2024, 1, 15, 16, 31, 0),
    )
    browse.note_visit(
        tmp_path,
        {"host": "news.ycombinator.com", "url": "https://news.ycombinator.com/", "title": "HN"},
        30,
        now=datetime(2024, 1, 15, 16, 32, 0),
    )
    ranked = browse.top_sites(tmp_path, now=t0, limit=10)
    assert [item["host"] for item in ranked] == ["google.com", "news.ycombinator.com"]
    assert ranked[0]["seconds"] == 60
    assert ranked[0]["visits"] == 2
    assert ranked[1]["seconds"] == 30


def test_top_sites_caps_at_ten(tmp_path):
    from datetime import datetime

    now = datetime(2024, 1, 15, 16, 30, 0)
    for index in range(12):
        host = f"site{index:02d}.example"
        browse.note_visit(
            tmp_path,
            {"host": host, "url": f"https://{host}/", "title": host},
            15 * (12 - index),
            now=now,
        )
    ranked = browse.top_sites(tmp_path, now=now)
    assert len(ranked) == 10
    assert ranked[0]["host"] == "site00.example"
    assert ranked[-1]["host"] == "site09.example"


def test_top_sites_skips_localhost_status_page(tmp_path):
    from datetime import datetime

    now = datetime(2024, 1, 15, 16, 30, 0)
    browse.note_visit(
        tmp_path,
        {"host": "127.0.0.1:8743", "url": "http://127.0.0.1:8743/", "title": "Your time today"},
        120,
        now=now,
    )
    browse.note_visit(
        tmp_path,
        {"host": "example.com", "url": "https://example.com/", "title": "Example"},
        15,
        now=now,
    )
    ranked = browse.top_sites(tmp_path, now=now)
    assert [item["host"] for item in ranked] == ["example.com"]


def test_note_visit_writes_browse_visits_to_sqlite(tmp_path):
    from datetime import datetime

    from timefence.tracking import SqliteUsageStore

    t0 = datetime(2024, 1, 15, 16, 30, 0)
    t1 = datetime(2024, 1, 15, 16, 30, 15)
    browse.note_visit(
        tmp_path,
        {
            "host": "www.youtube.com",
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "title": "Loki",
            "browser": "chrome",
        },
        15,
        now=t0,
    )
    browse.note_visit(
        tmp_path,
        {
            "host": "www.youtube.com",
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
            "title": "Loki",
            "browser": "chrome",
        },
        15,
        now=t1,
    )
    store = SqliteUsageStore(tmp_path / "screen_time.sqlite")
    visits = store.get_browse_visits("2024-01-15")
    assert len(visits) == 1
    assert visits[0]["host"] == "www.youtube.com"
    assert visits[0]["usage_seconds"] == 30
    assert visits[0]["browser"] == "chrome"
    assert visits[0]["last_seen"] == "16:30:15"


def test_load_browse_state_prefers_sqlite_over_json(tmp_path):
    from datetime import datetime
    import json

    when = datetime(2024, 1, 15, 16, 30)
    browse.note_visit(
        tmp_path,
        {"host": "example.com", "url": "https://example.com/", "title": "Example"},
        15,
        now=when,
    )
    path = tmp_path / "browse" / "2024-01-15.json"
    payload = json.loads(path.read_text())
    payload["visits"][0]["usage_seconds"] = 999
    path.write_text(json.dumps(payload))
    state = browse.load_browse_state(tmp_path, now=when)
    assert state["visits"][0]["usage_seconds"] == 15


def test_json_browse_visits_are_seeded_into_sqlite(tmp_path):
    from datetime import datetime
    import json

    from timefence.tracking import SqliteUsageStore

    when = datetime(2024, 1, 15, 16, 30)
    path = tmp_path / "browse" / "2024-01-15.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "date": "2024-01-15",
                "visits": [
                    {
                        "host": "www.youtube.com",
                        "url": "https://www.youtube.com/watch?v=abc",
                        "title": "Clip",
                        "first_seen": "16:00:00",
                        "last_seen": "16:00:30",
                        "usage_seconds": 30,
                    }
                ],
            }
        )
    )
    state = browse.load_browse_state(tmp_path, now=when)
    assert state["visits"][0]["usage_seconds"] == 30
    store = SqliteUsageStore(tmp_path / "screen_time.sqlite")
    assert store.get_browse_visits("2024-01-15")[0]["url"] == "https://www.youtube.com/watch?v=abc"
