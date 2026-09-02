"""URL-contains matching shared by website resources and AppleScript adapters."""

DEFAULT_URL_CONTAINS = ("youtube.com/", "youtu.be/")

KNOWN_BROWSERS = ("chrome", "safari", "edge", "firefox", "brave")


def pattern_list(resource, key, default=()):
    values = (resource or {}).get(key)
    if values is None:
        return list(default)
    return [str(item) for item in values]


def url_matches(url, resource, default_contains=DEFAULT_URL_CONTAINS):
    if not url:
        return False
    contains = pattern_list(resource, "url_contains", default_contains)
    excludes = pattern_list(resource, "url_excludes", ())
    if not any(token in url for token in contains):
        return False
    return not any(token in url for token in excludes)


def normalize_browser_names(value):
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return []
    out = []
    seen = set()
    for item in items:
        name = str(item or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def requested_browsers(resource=None, cfg=None, os_name=None):
    """Resource `browsers` / `browser`, else top-level config, else OS default."""
    from ..platform.detect import current_os

    if isinstance(resource, dict):
        names = normalize_browser_names(resource.get("browsers"))
        if names:
            return names
        names = normalize_browser_names(resource.get("browser"))
        if names:
            return names
    if isinstance(cfg, dict):
        names = normalize_browser_names(cfg.get("browsers"))
        if names:
            return names
        names = normalize_browser_names(cfg.get("browser"))
        if names:
            return names
    return default_browsers(os_name or current_os())


def default_browsers(os_name=None):
    """Browsers we try when config does not say. Chrome-only keeps existing tests/behavior."""
    from ..platform.detect import DARWIN, LINUX, WINDOWS, current_os

    name = current_os(os_name)
    if name == DARWIN:
        return ["chrome"]
    if name == WINDOWS:
        return ["chrome", "edge"]
    if name == LINUX:
        return ["chrome", "firefox"]
    return ["chrome"]
