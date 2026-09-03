"""Map an observed activity onto a listed TimeFence resource.

Identity is (resource_type, resource_id). Listed apps match on resource_id
or match_ids. Unlisted foreground apps still use the observed bundle ID.
"""

from ..identity import (
    RESOURCE_TYPE_APP,
    RESOURCE_TYPE_WEBSITE,
    find_listed_resource,
    listed_resources,
    match_ids_for,
    resource_id_of,
    resource_type_of,
    website_id,
)
from ..models.activity import KIND_APP, KIND_WEBSITE, Activity


def _enabled_resources(resources):
    out = []
    for resource in listed_resources(resources):
        if not resource.get("enabled", True):
            continue
        out.append(resource)
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
    """Bundle IDs this listed app matches, including match_ids."""
    if resource_type_of(resource) != RESOURCE_TYPE_APP:
        return _string_list((resource or {}).get("bundle_ids"))
    return match_ids_for(resource)


def app_ids_for(resource, os_name=None):
    """App identifiers for this OS: `app_ids.<os>`, else macOS bundle IDs, else `executables`."""
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
    """Return the listed app resource whose resource_id or match_ids include this app id."""
    key = str(app_id or "").strip().lower()
    if not key:
        return None
    for resource in _enabled_resources(resources):
        if resource_type_of(resource) != RESOURCE_TYPE_APP:
            continue
        configured = [item.lower() for item in app_ids_for(resource, os_name=os_name)]
        if key in configured:
            return resource
    listed = find_listed_resource(resources, RESOURCE_TYPE_APP, app_id)
    if listed is not None and listed.get("enabled", True):
        return listed
    return None


def find_resource_by_bundle_id(resources, bundle_id):
    """macOS alias for find_resource_by_app_id."""
    return find_resource_by_app_id(resources, bundle_id)


def find_resource_by_url(resources, url):
    """Match a website or video_category resource by url_contains / url_excludes."""
    text = str(url or "")
    if not text:
        return None
    host = website_id(text)
    for resource in _enabled_resources(resources):
        rtype = resource_type_of(resource)
        if rtype == RESOURCE_TYPE_WEBSITE and resource_id_of(resource).lower() == host:
            contains = resource.get("url_contains")
            if not isinstance(contains, list) or not contains:
                return resource
        contains = resource.get("url_contains")
        if not isinstance(contains, list) or not contains:
            continue
        if not any(token and token in text for token in contains):
            continue
        excludes = resource.get("url_excludes") or []
        if any(token and token in text for token in excludes):
            continue
        return resource
    return None


def find_resource_for_activity(resources, activity):
    """Dispatch on Activity.kind. Returns None when the app/URL is not listed."""
    if activity is None:
        return None
    if not isinstance(activity, Activity):
        return None
    if activity.kind == KIND_APP:
        return find_resource_by_app_id(resources, activity.identifier)
    if activity.kind == KIND_WEBSITE:
        return find_resource_by_url(resources, activity.identifier)
    return None


def usage_identity_for_activity(resources, activity):
    """(resource_type, resource_id) used in SQLite for this observation.

    Listed apps use the configured resource_id. Any other foreground app is
    stored under its bundle ID. Unmatched websites stay None.
    """
    match = find_resource_for_activity(resources, activity)
    if match is not None:
        return resource_type_of(match), resource_id_of(match)
    if activity is None or activity.kind != KIND_APP:
        return None
    identifier = str(activity.identifier or "").strip()
    if not identifier:
        return None
    return RESOURCE_TYPE_APP, identifier.replace("/", "_").replace("\\", "_")


def usage_id_for_activity(resources, activity):
    """Return resource_id only. Prefer usage_identity_for_activity for new code."""
    identity = usage_identity_for_activity(resources, activity)
    if identity is None:
        return None
    return identity[1]


def uses_app_capture(resource):
    """True if the controller should use the screen-time (app) path."""
    if not isinstance(resource, dict):
        return False
    if resource_type_of(resource) == RESOURCE_TYPE_APP:
        return True
    if bundle_ids_for(resource) or resource.get("app_ids") or resource.get("executables"):
        return True
    return False


def uses_video_capture(resource):
    return resource_type_of(resource) == "video_category"
