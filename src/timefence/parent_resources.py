"""Add and edit listed resources from the parent Resources page.

Limits still only patches schedules on resources that already exist.
This module is what creates, renames, enables, and removes them.
"""

from .config import validate_config
from .identity import (
    RESOURCE_TYPE_APP,
    RESOURCE_TYPE_VIDEO_CATEGORY,
    RESOURCE_TYPE_WEBSITE,
    YOUTUBE_SHORTS_RESOURCE_ID,
    YOUTUBE_VIDEOS_RESOURCE_ID,
    default_display_name,
    ensure_resource,
    listed_resources,
    match_ids_for,
    resource_id_of,
    resource_key,
    resource_type_of,
    website_id,
)

TYPE_LABELS = {
    RESOURCE_TYPE_APP: "App",
    RESOURCE_TYPE_WEBSITE: "Website",
    RESOURCE_TYPE_VIDEO_CATEGORY: "Video",
}

_TYPE_ORDER = (RESOURCE_TYPE_APP, RESOURCE_TYPE_WEBSITE, RESOURCE_TYPE_VIDEO_CATEGORY)


class UnknownResource(ValueError):
    pass


class DuplicateResource(ValueError):
    pass


def _bump_revision(existing):
    cfg = dict(existing or {})
    cfg["version"] = 1
    try:
        cfg["revision"] = int(cfg.get("revision") or 0) + 1
    except (TypeError, ValueError):
        cfg["revision"] = 1
    return cfg


def _string_list(value):
    if value is None or value == "":
        return []
    if isinstance(value, str):
        raw = value.replace(";", ",").split(",")
    elif isinstance(value, list):
        raw = value
    else:
        raise ValueError("match_ids must be a list of identifiers")
    out = []
    seen = set()
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def normalize_identity(resource_type, resource_id):
    resource_type = str(resource_type or "").strip()
    resource_id = str(resource_id or "").strip()
    if resource_type not in TYPE_LABELS:
        raise ValueError("resource_type must be app, website, or video_category")
    if resource_type == RESOURCE_TYPE_WEBSITE:
        resource_id = website_id(resource_id)
    if resource_type == RESOURCE_TYPE_VIDEO_CATEGORY and resource_id not in (
        YOUTUBE_VIDEOS_RESOURCE_ID,
        YOUTUBE_SHORTS_RESOURCE_ID,
    ):
        raise ValueError("Video resources must be youtube_videos or youtube_shorts")
    if not resource_id:
        raise ValueError("resource_id is required")
    return resource_type, resource_id


def _find_index(resources, resource_type, resource_id):
    needle = str(resource_id or "").strip().lower()
    for index, item in enumerate(resources):
        if resource_type_of(item) != resource_type:
            continue
        if resource_id_of(item).lower() == needle:
            return index
    return None


def _default_policy():
    return {
        "default": {
            "daily_limit_minutes": 0,
            "allowed_windows": [{"id": "all_day", "start": "00:00", "end": "24:00"}],
        }
    }


def _video_fields(resource_id):
    if resource_id == YOUTUBE_SHORTS_RESOURCE_ID:
        return {
            "module": "youtube",
            "browsers": ["chrome", "safari"],
            "url_contains": ["youtube.com/shorts"],
        }
    return {
        "module": "youtube",
        "browsers": ["chrome", "safari"],
        "url_contains": ["youtube.com/watch", "youtu.be/"],
        "url_excludes": ["youtube.com/shorts"],
    }


def extra_match_ids(resource):
    rid = resource_id_of(resource).lower()
    return [item for item in match_ids_for(resource) if item.lower() != rid]


def _managed_row(resource, *, listed, sqlite_name=""):
    rtype, rid = resource_key(resource)
    display = str(resource.get("display_name") or sqlite_name or "").strip() or default_display_name(
        rtype, rid
    )
    return {
        "resource_type": rtype,
        "resource_id": rid,
        "display_name": display,
        "type_label": TYPE_LABELS.get(rtype, rtype),
        "enabled": bool(resource.get("enabled", True)) if listed else False,
        "listed": listed,
        "match_ids": extra_match_ids(resource) if listed and rtype == RESOURCE_TYPE_APP else [],
    }


def list_managed_resources(cfg, store=None):
    listed = listed_resources(cfg)
    seen = set()
    rows = []
    for resource in listed:
        rtype, rid = resource_key(resource)
        sqlite_name = ""
        if store is not None:
            found = store.get_resource(rtype, rid)
            if found:
                sqlite_name = found.get("display_name") or ""
        rows.append(_managed_row(resource, listed=True, sqlite_name=sqlite_name))
        seen.add((rtype, rid.lower()))
    if store is not None:
        for item in store.list_resources():
            rtype = str(item.get("resource_type") or "").strip()
            rid = str(item.get("resource_id") or "").strip()
            if not rtype or not rid or (rtype, rid.lower()) in seen:
                continue
            rows.append(
                _managed_row(
                    {
                        "resource_type": rtype,
                        "resource_id": rid,
                        "display_name": item.get("display_name") or "",
                        "enabled": False,
                    },
                    listed=False,
                )
            )
    rows.sort(
        key=lambda row: (
            0 if row["listed"] else 1,
            _TYPE_ORDER.index(row["resource_type"]) if row["resource_type"] in _TYPE_ORDER else 9,
            str(row["display_name"]).lower(),
            str(row["resource_id"]).lower(),
        )
    )
    return {"resources": rows}


def sync_store(store, resource_type, resource_id, display_name=""):
    if store is None:
        return
    ensure_resource(
        store,
        resource_type,
        resource_id,
        display_name=display_name or default_display_name(resource_type, resource_id),
    )


def create_resource(cfg, payload):
    if not isinstance(payload, dict):
        raise ValueError("Request must be a JSON object")
    resource_type, resource_id = normalize_identity(payload.get("resource_type"), payload.get("resource_id"))
    resources = list(listed_resources(cfg))
    if _find_index(resources, resource_type, resource_id) is not None:
        raise DuplicateResource(f"Already tracking {resource_type}/{resource_id}")
    display = str(payload.get("display_name") or "").strip() or default_display_name(resource_type, resource_id)
    resource = {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "display_name": display,
        "enabled": bool(payload.get("enabled", True)),
        "policy": _default_policy(),
    }
    if resource_type == RESOURCE_TYPE_APP:
        extras = _string_list(payload.get("match_ids"))
        match_ids = []
        seen = {resource_id.lower()}
        for item in extras:
            if item.lower() in seen:
                continue
            seen.add(item.lower())
            match_ids.append(item)
        if match_ids:
            resource["match_ids"] = [resource_id, *match_ids]
    elif resource_type == RESOURCE_TYPE_WEBSITE:
        resource["browsers"] = ["chrome", "safari"]
    else:
        resource.update(_video_fields(resource_id))
    cfg = _bump_revision(cfg)
    cfg["resources"] = resources + [resource]
    return validate_config(cfg), resource


def update_resource(cfg, resource_type, resource_id, payload):
    if not isinstance(payload, dict):
        raise ValueError("Request must be a JSON object")
    resource_type, resource_id = normalize_identity(resource_type, resource_id)
    resources = list(listed_resources(cfg))
    index = _find_index(resources, resource_type, resource_id)
    if index is None:
        raise UnknownResource(f"Unknown resource {resource_type}/{resource_id}")
    resource = dict(resources[index])
    if "display_name" in payload:
        display = str(payload.get("display_name") or "").strip()
        if not display:
            raise ValueError("display_name must be a non-empty string")
        resource["display_name"] = display
    if "enabled" in payload:
        resource["enabled"] = bool(payload.get("enabled"))
    if "match_ids" in payload:
        if resource_type != RESOURCE_TYPE_APP:
            raise ValueError("match_ids are only used for apps")
        extras = _string_list(payload.get("match_ids"))
        if extras:
            resource["match_ids"] = [resource_id, *[item for item in extras if item.lower() != resource_id.lower()]]
        else:
            resource.pop("match_ids", None)
    resources[index] = resource
    cfg = _bump_revision(cfg)
    cfg["resources"] = resources
    return validate_config(cfg), resource


def rename_observed(store, resource_type, resource_id, display_name):
    resource_type, resource_id = normalize_identity(resource_type, resource_id)
    display = str(display_name or "").strip()
    if not display:
        raise ValueError("display_name must be a non-empty string")
    sync_store(store, resource_type, resource_id, display)
    return {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "display_name": display,
        "type_label": TYPE_LABELS.get(resource_type, resource_type),
        "enabled": False,
        "listed": False,
        "match_ids": [],
    }


def delete_resource(cfg, resource_type, resource_id):
    resource_type, resource_id = normalize_identity(resource_type, resource_id)
    resources = list(listed_resources(cfg))
    index = _find_index(resources, resource_type, resource_id)
    if index is None:
        raise UnknownResource(f"Unknown resource {resource_type}/{resource_id}")
    resources.pop(index)
    cfg = _bump_revision(cfg)
    cfg["resources"] = resources
    return validate_config(cfg)
