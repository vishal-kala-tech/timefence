from datetime import datetime

from timefence.browse import note_visit
from timefence.history import format_seen, format_summary, summarize
from timefence.usage import add_usage
from tests.helpers import make_config, make_resource

WHEN = datetime(2024, 1, 15, 16, 30, 0)
LATER = datetime(2024, 1, 15, 16, 30, 45)


def test_format_seen_uses_plain_times():
    assert format_seen("16:30:00") == "4:30 PM"
    assert format_seen("07:05:12") == "7:05 AM"
    assert format_seen("") is None


def test_summarize_videos_and_sites_in_sentences(app_dir):
    add_usage(
        app_dir / "state",
        "youtube",
        15,
        window_id="all_day",
        now=WHEN,
        video={
            "id": "aaaaaaaaaaa",
            "title": "First",
            "channel": "Channel A",
            "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        },
    )
    add_usage(
        app_dir / "state",
        "youtube",
        15,
        window_id="all_day",
        now=LATER,
        video={
            "id": "bbbbbbbbbbb",
            "title": "Second",
            "url": "https://www.youtube.com/watch?v=bbbbbbbbbbb",
        },
    )
    note_visit(
        app_dir / "state",
        {
            "host": "www.example.com",
            "url": "https://www.example.com/",
            "title": "Example Domain",
        },
        15,
        now=WHEN,
    )
    text = format_summary(
        summarize(
            make_config(resources={"youtube": make_resource(display_name="YouTube")}),
            app_dir / "state",
            now=WHEN,
        ),
        now=WHEN,
    )
    assert "Here is what was watched and visited on Monday, January 15, 2024." in text
    assert "YouTube: 2 videos were watched, for a total of 30 seconds." in text
    assert 'From 4:30 PM to 4:30 PM' not in text
    assert 'At 4:30 PM, "First" by Channel A was watched for 15 seconds.' in text
    assert 'At 4:30 PM, "Second" was watched for 15 seconds.' in text
    assert "Websites: 1 page was visited, for a total of 15 seconds." in text
    assert 'At 4:30 PM, example.com ("Example Domain") was visited for 15 seconds.' in text
    assert "YouTube Shorts" not in text


def test_empty_history_is_a_sentence(app_dir):
    text = format_summary(summarize({}, app_dir / "state", now=WHEN), now=WHEN)
    assert "No videos or websites were recorded." in text
