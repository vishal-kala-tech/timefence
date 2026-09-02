"""Website resource adapter (YouTube watch vs Shorts, or any url_contains site).

Tab inspect/close is delegated to `timefence.browsers`. This module owns
YouTube URL parsing, oEmbed metadata, and the inspect payload the controller
expects (`url`, `playback`, `video`).

Chrome-as-app and YouTube-as-website stay separate budgets. Set
`browsers: ["chrome", "safari"]` on a website resource to cover both.
"""

import json
import logging
import re
import subprocess
from collections import OrderedDict
from urllib.error import URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

from ..browsers import close_matching_tabs, read_matching_tab, url_matches as _url_matches
from ..browsers.macos.applescript import PLAYBACK_JS, applescript_string
from ..browsers.macos.chrome import close_script as chrome_close_script
from ..browsers.macos.chrome import inspect_script as chrome_inspect_script
from ..browsers.matching import DEFAULT_URL_CONTAINS

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
TITLE_SUFFIX = " - YouTube"
OEMBED_URL = "https://www.youtube.com/oembed?format=json&url="
METADATA_CACHE_SIZE = 20
_metadata_cache = OrderedDict()

# Re-exports so existing tests and scripts keep importing from this module.
inspect_script = chrome_inspect_script
close_script = chrome_close_script
_applescript_string = applescript_string


def _patterns(resource, key, default):
    values = (resource or {}).get(key)
    if values is None:
        return list(default)
    return [str(item) for item in values]


def url_matches(url, resource):
    return _url_matches(url, resource, default_contains=DEFAULT_URL_CONTAINS)


def clean_title(title):
    text = (title or "").strip()
    if text in ("missing value", "YouTube"):
        return ""
    if text.endswith(TITLE_SUFFIX):
        text = text[: -len(TITLE_SUFFIX)].strip()
    return text


def clean_channel(name):
    text = " ".join((name or "").split())
    if text.lower() in ("missing value", "undefined", "null"):
        return ""
    return text


def parse_video(url, title="", channel=""):
    """Canonical watch vs Shorts URL. Invalid ids return None so they never enter history."""
    if not url:
        return None
    parsed = urlparse(url.strip())
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    video_id = None
    kind = "watch"

    if "youtu.be" in host:
        video_id = path.strip("/").split("/")[0]
    else:
        parts = [part for part in path.split("/") if part]
        lowered = [part.lower() for part in parts]
        if "shorts" in lowered:
            idx = lowered.index("shorts")
            if idx + 1 < len(parts):
                video_id = parts[idx + 1]
                kind = "shorts"
        elif "embed" in lowered:
            idx = lowered.index("embed")
            if idx + 1 < len(parts):
                video_id = parts[idx + 1]
        elif "watch" in lowered:
            video_id = (parse_qs(parsed.query).get("v") or [None])[0]
        else:
            video_id = (parse_qs(parsed.query).get("v") or [None])[0]

    if not video_id:
        return None
    video_id = video_id.split("?")[0].split("&")[0].strip()
    if not VIDEO_ID_RE.fullmatch(video_id):
        return None

    if kind == "shorts":
        canonical = f"https://www.youtube.com/shorts/{video_id}"
    else:
        canonical = f"https://www.youtube.com/watch?v={video_id}"

    return {
        "id": video_id,
        "title": clean_title(title),
        "channel": clean_channel(channel),
        "url": canonical,
    }


def _get_json(url):
    request = Request(url, headers={"User-Agent": "TimeFence/1.0"})
    with urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_oembed(url):
    if not url:
        return None
    try:
        data = _get_json(OEMBED_URL + quote(url, safe=""))
    except (OSError, URLError, TimeoutError, ValueError) as exc:
        logging.debug("YouTube oEmbed failed for %s: %s", url, exc)
        return None
    if not isinstance(data, dict):
        return None
    return {
        "title": clean_title(data.get("title") or ""),
        "channel": clean_channel(data.get("author_name") or ""),
    }


def lookup_metadata(video_id):
    """Return cached title/channel, fetching oEmbed only on a cache miss.

    Keeps the last METADATA_CACHE_SIZE successful lookups so a video watched
    across 15-second polls does not hit YouTube again. Failed fetches are not
    cached, so the next poll can retry.
    """
    if not video_id:
        return None
    if video_id in _metadata_cache:
        _metadata_cache.move_to_end(video_id)
        return _metadata_cache[video_id]
    result = fetch_oembed(f"https://www.youtube.com/watch?v={video_id}")
    if result is None:
        return None
    _metadata_cache[video_id] = result
    while len(_metadata_cache) > METADATA_CACHE_SIZE:
        _metadata_cache.popitem(last=False)
    return result


def _apply_metadata(video, resource=None):
    if not video:
        return video
    extra = lookup_metadata(video.get("id"))
    if not extra:
        return video
    if extra.get("channel"):
        video["channel"] = extra["channel"]
    if extra.get("title") and not video.get("title"):
        video["title"] = extra["title"]
    return video


def parse_playback(value):
    text = str(value or "").strip().strip('"').lower()
    if text in ("paused", "pause"):
        return "paused"
    return "playing"


def active_script(resource):
    return inspect_script(resource)


ACTIVE_SCRIPT = inspect_script({})
CLOSE_SCRIPT = close_script({})


def inspect(resource):
    """Front tab of the first configured browser that is frontmost and matches the URL."""
    tab = read_matching_tab(resource, run=subprocess.run)
    if tab is None:
        return None
    url = tab.url
    if url in ("", "missing value", "NO", "YES") or not url_matches(url, resource):
        return None
    title = clean_title(tab.title)
    playback = parse_playback(tab.playback)
    video = _apply_metadata(parse_video(url, title), resource)
    return {
        "url": url,
        "title": (video or {}).get("title") or title,
        "channel": (video or {}).get("channel") or "",
        "playback": playback,
        "video": video,
        "browser": tab.browser,
    }


def is_active(resource):
    return inspect(resource) is not None


def enforce(resource):
    close_matching_tabs(resource, run=subprocess.run)
