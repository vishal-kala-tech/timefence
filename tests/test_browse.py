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
