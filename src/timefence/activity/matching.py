"""Map an observed activity onto a TimeFence resource.

On macOS, `bundle_ids` is the identifier. Other OSes use `app_ids.<os>` or
`executables`. URL contains/excludes are for website activity (browser
adapters or a future extension). First enabled match in `rules.json`
insertion order wins.
"""

from ..models.activity import KIND_APP, KIND_WEBSITE, Activity


def _enabled_resources(resources):
    if not isinstance(resources, dict):
        return []
    out = []
    for name, resource in resources.items():
        if not isinstance(resource, dict):
            continue
        if not resource.get("enabled", True):
            continue
        out.append((name, resource))
    return out


def _string_list(values):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    out = []
    seen = set()
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def bundle_ids_for(resource):
    """Configured bundle IDs, de-duplicated, original spelling preserved."""
    return _string_list((resource or {}).get("bundle_ids"))


def app_ids_for(resource, os_name=None):
    """App identifiers for this OS: `app_ids.<os>`, else macOS `bundle_ids`, else `executables`."""
    from ..platform.detect import DARWIN, current_os, os_aliases

    os_name = current_os(os_name)
    mapping = (resource or {}).get("app_ids")
    if isinstance(mapping, dict):
        for key in os_aliases(os_name):
            if key in mapping:
                return _string_list(mapping.get(key))
        return []
    if os_name == DARWIN:
        ids = bundle_ids_for(resource)
        if ids:
            return ids
    return _string_list((resource or {}).get("executables"))


def find_resource_by_app_id(resources, app_id, os_name=None):
    """Return (resource_id, resource) for the first enabled resource that lists this app id."""
    key = str(app_id or "").strip().lower()
    if not key:
        return None
    for name, resource in _enabled_resources(resources):
        configured = [item.lower() for item in app_ids_for(resource, os_name=os_name)]
        if key in configured:
            return name, resource
    return None


def find_resource_by_bundle_id(resources, bundle_id):
    """macOS alias for find_resource_by_app_id."""
    return find_resource_by_app_id(resources, bundle_id)


def find_resource_by_url(resources, url):
    """Match a website resource by url_contains / url_excludes.

    Browser adapters and UsageTracker (when Observation.activity.kind is
    website) both use this. The OS activity monitor does not scrape URLs.
    """
    text = str(url or "")
    if not text:
        return None
    for name, resource in _enabled_resources(resources):
        if str(resource.get("type") or "").lower() not in ("website", "web", ""):
            if resource.get("url_contains") is None:
                continue
        contains = resource.get("url_contains")
        if not isinstance(contains, list) or not contains:
            continue
        if not any(token and token in text for token in contains):
            continue
        excludes = resource.get("url_excludes") or []
        if any(token and token in text for token in excludes):
            continue
        return name, resource
    return None


def find_resource_for_activity(resources, activity):
    """Dispatch on Activity.kind. Unknown kinds count as unmatched (no usage)."""
    if activity is None:
        return None
    if not isinstance(activity, Activity):
        return None
    if activity.kind == KIND_APP:
        return find_resource_by_app_id(resources, activity.identifier)
    if activity.kind == KIND_WEBSITE:
        return find_resource_by_url(resources, activity.identifier)
    return None


def uses_app_capture(resource):
    """True if the controller should use the screen-time (app-id) path.

    Resources with `bundle_ids`, `app_ids`, `executables`, or `type: app`
    skip the old per-resource inspect/add-interval loop. Website resources
    stay on the browser-tab adapter.
    """
    if not isinstance(resource, dict):
        return False
    if bundle_ids_for(resource) or resource.get("app_ids") or resource.get("executables"):
        return True
    return str(resource.get("type") or "").lower() == "app"
