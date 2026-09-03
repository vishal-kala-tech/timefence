from timefence.identity import (
    RESOURCE_TYPE_APP,
    RESOURCE_TYPE_VIDEO_CATEGORY,
    RESOURCE_TYPE_WEBSITE,
    YOUTUBE_SHORTS_RESOURCE_ID,
    YOUTUBE_VIDEOS_RESOURCE_ID,
)
from timefence.parent_resources import (
    DuplicateResource,
    UnknownResource,
    create_resource,
    delete_resource,
    extra_match_ids,
    list_managed_resources,
    update_resource,
)
from timefence.tracking import SqliteUsageStore
from tests.helpers import make_config, make_resource


def test_create_app_and_rename(tmp_path):
    cfg = make_config(resources=[])
    cfg, resource = create_resource(
        cfg,
        {
            "resource_type": RESOURCE_TYPE_APP,
            "resource_id": "com.apple.Terminal",
            "display_name": "Mac Terminal",
            "match_ids": "com.apple.Terminal, Terminal",
        },
    )
    assert resource["resource_id"] == "com.apple.Terminal"
    assert resource["display_name"] == "Mac Terminal"
    assert extra_match_ids(resource) == ["Terminal"]
    cfg, resource = update_resource(
        cfg,
        RESOURCE_TYPE_APP,
        "com.apple.Terminal",
        {"display_name": "Terminal", "enabled": False},
    )
    assert resource["display_name"] == "Terminal"
    assert resource["enabled"] is False
    rows = list_managed_resources(cfg)["resources"]
    assert rows[0]["listed"] is True
    assert rows[0]["display_name"] == "Terminal"


def test_create_website_normalizes_domain():
    cfg = make_config(resources=[])
    cfg, resource = create_resource(
        cfg,
        {"resource_type": RESOURCE_TYPE_WEBSITE, "resource_id": "https://www.github.com/cursor"},
    )
    assert resource["resource_id"] == "github.com"
    assert resource["display_name"] == "GitHub"
    assert resource["browsers"] == ["chrome", "safari"]


def test_create_video_category_fills_youtube_filters():
    cfg = make_config(resources=[])
    cfg, videos = create_resource(
        cfg,
        {"resource_type": RESOURCE_TYPE_VIDEO_CATEGORY, "resource_id": YOUTUBE_VIDEOS_RESOURCE_ID},
    )
    assert videos["module"] == "youtube"
    assert "youtube.com/watch" in videos["url_contains"]
    cfg, shorts = create_resource(
        cfg,
        {"resource_type": RESOURCE_TYPE_VIDEO_CATEGORY, "resource_id": YOUTUBE_SHORTS_RESOURCE_ID},
    )
    assert shorts["url_contains"] == ["youtube.com/shorts"]


def test_duplicate_and_unknown():
    cfg = make_config(resources=[make_resource(resource_id="com.google.Chrome", display_name="Chrome")])
    try:
        create_resource(cfg, {"resource_type": RESOURCE_TYPE_APP, "resource_id": "com.google.Chrome"})
        assert False, "expected duplicate"
    except DuplicateResource:
        pass
    try:
        update_resource(cfg, RESOURCE_TYPE_APP, "com.apple.Terminal", {"display_name": "Terminal"})
        assert False, "expected unknown"
    except UnknownResource:
        pass


def test_delete_resource_keeps_others():
    cfg = make_config(
        resources=[
            make_resource(resource_id="com.google.Chrome", display_name="Chrome"),
            make_resource(resource_type=RESOURCE_TYPE_WEBSITE, resource_id="github.com", display_name="GitHub"),
        ]
    )
    cfg = delete_resource(cfg, RESOURCE_TYPE_APP, "com.google.Chrome")
    assert [item["resource_id"] for item in cfg["resources"]] == ["github.com"]


def test_list_includes_observed_sqlite_rows(tmp_path):
    cfg = make_config(resources=[make_resource(resource_id="com.google.Chrome", display_name="Google Chrome")])
    store = SqliteUsageStore(tmp_path / "screen_time.sqlite")
    store.ensure_resource(RESOURCE_TYPE_APP, "com.apple.Terminal", display_name="Terminal", updated_at="t")
    rows = list_managed_resources(cfg, store)["resources"]
    listed = [row for row in rows if row["listed"]]
    seen = [row for row in rows if not row["listed"]]
    assert listed[0]["resource_id"] == "com.google.Chrome"
    assert seen[0]["resource_id"] == "com.apple.Terminal"
    assert seen[0]["display_name"] == "Terminal"
