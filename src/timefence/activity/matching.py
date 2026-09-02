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


def bundle_ids_for(resource):
    values = (resource or {}).get("bundle_ids")
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


def find_resource_by_bundle_id(resources, bundle_id):
    """Return (resource_id, resource) for the first enabled resource that lists this bundle ID."""
    key = str(bundle_id or "").strip().lower()
    if not key:
        return None
    for name, resource in _enabled_resources(resources):
        configured = [item.lower() for item in bundle_ids_for(resource)]
        if key in configured:
            return name, resource
    return None


def find_resource_by_url(resources, url):
    """Match a website resource by url_contains / url_excludes. Used when a browser extension reports a URL."""
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
    if activity is None:
        return None
    if not isinstance(activity, Activity):
        return None
    if activity.kind == KIND_APP:
        return find_resource_by_bundle_id(resources, activity.identifier)
    if activity.kind == KIND_WEBSITE:
        return find_resource_by_url(resources, activity.identifier)
    return None


def uses_app_capture(resource):
    if not isinstance(resource, dict):
        return False
    if bundle_ids_for(resource):
        return True
    return str(resource.get("type") or "").lower() == "app"
