import logging
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional, Tuple

from ..activity.matching import usage_identity_for_activity
from ..grants import effective_daily_limit
from ..identity import (
    IDENTIFIER_BUNDLE_ID,
    RESOURCE_TYPE_APP,
    app_resource_id,
    default_display_name,
    ensure_resource,
    find_listed_resource,
    is_bundle_id,
    listed_resources,
    resource_id_of,
    resource_type_of,
)
from ..models.activity import Observation
from ..models.usage import SessionRecord, TodayUsage, UsageSnapshot
from ..policy import resolve_policy
from .usage_store import UsageStore

MAX_COUNTABLE_INTERVAL_SECONDS = 30
DEFAULT_IDLE_THRESHOLD_SECONDS = 120

ResourceKey = Tuple[str, str]


def format_timestamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return value.replace(microsecond=0).isoformat()


def countable_seconds(elapsed, max_countable=MAX_COUNTABLE_INTERVAL_SECONDS):
    """Credit wall-clock elapsed, or 0 if the gap looks like sleep/stall."""
    try:
        elapsed = float(elapsed)
    except (TypeError, ValueError):
        return 0
    if elapsed <= 0:
        return 0
    if elapsed > float(max_countable):
        return 0
    return int(round(elapsed))


@dataclass
class ScreenTimeSettings:
    enabled: bool = True
    poll_interval_seconds: int = 10
    idle_threshold_seconds: float = DEFAULT_IDLE_THRESHOLD_SECONDS
    max_countable_interval_seconds: float = MAX_COUNTABLE_INTERVAL_SECONDS


@dataclass
class TickResult:
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    increment_seconds: int = 0
    total_seconds: int = 0
    session_started: bool = False
    session_ended: bool = False
    idle: bool = False
    interrupted: bool = False
    identifier: str = ""
    pid: Optional[int] = None

    @property
    def key(self) -> Optional[ResourceKey]:
        if not self.resource_type or not self.resource_id:
            return None
        return (self.resource_type, self.resource_id)


class UsageTracker:
    """Turns activity observations into daily usage and sessions. Does not enforce policy.

    This class credits the **app** layer only (physical foreground time).
    Website and video_category attribution is recorded elsewhere so screen
    time is never the sum of those layers.
    """

    def __init__(self, store: UsageStore):
        self.store = store
        self._last_poll = None
        self._session_id = None
        self._session_resource_type = None
        self._session_resource_id = None
        self._session_started_at = None
        self._session_duration = 0
        self._session_identifier = ""
        self._session_pid = None
        self._was_idle = False

    def close_orphaned_sessions(self, now=None):
        """Close rows left open after a crash. Do not add the downtime as usage."""
        now = now or datetime.now()
        stamp = format_timestamp(now)
        for session in self.store.get_open_sessions():
            self.store.end_session(session.id, stamp, session.duration_seconds)
        self._clear_session()

    def close(self, now=None):
        now = now or datetime.now()
        self._end_session(now, reason="stopped")
        self.close_orphaned_sessions(now)

    def apply(self, observation: Observation, resources, settings: ScreenTimeSettings) -> TickResult:
        """Turn one monitor snapshot into app-layer session/usage updates.

        Rules of thumb:
        - Elapsed time is (now - previous poll), never the configured interval.
        - Gaps larger than max_countable_interval_seconds are sleep/stall:
          end the session, do not credit the gap.
        - Idle/lock: do not credit this interval; end the session.
        - Credit the app that was in front *during* the interval, then switch
          to whoever is in front now.
        - Listed apps use the configured resource_id; any other foreground app
          is stored under its bundle ID.
        """
        now = observation.timestamp
        idle = observation.idle_seconds >= float(settings.idle_threshold_seconds)
        locked = bool(observation.screen_locked)
        previous_poll = self._last_poll
        elapsed = 0.0
        interrupted = False
        if previous_poll is not None:
            elapsed = (now - previous_poll).total_seconds()
            if elapsed < 0:
                elapsed = 0.0
            if elapsed > float(settings.max_countable_interval_seconds):
                interrupted = True
        self._last_poll = now

        activity = None if (idle or locked) else observation.resolved_activity()
        current = usage_identity_for_activity(resources, activity) if activity else None
        identifier = ""
        pid = None
        if activity is not None:
            identifier = activity.identifier
            pid = activity.pid
        elif observation.frontmost is not None:
            identifier = observation.frontmost.bundle_id
            pid = observation.frontmost.pid

        result = TickResult(
            resource_type=current[0] if current else None,
            resource_id=current[1] if current else None,
            idle=idle,
            interrupted=interrupted,
            identifier=identifier,
            pid=pid,
        )

        if idle and not self._was_idle:
            _log("SCREEN_TIME_IDLE", idle_seconds=int(observation.idle_seconds))
        self._was_idle = idle or locked

        if interrupted:
            result.session_ended = self._end_session(now, reason="interrupted")
            if current:
                result.session_started = self._start_session(
                    current[0], current[1], now, activity, resources=resources
                )
            return result

        if idle or locked:
            result.session_ended = self._end_session(now, reason="locked" if locked else "idle")
            return result

        counted = countable_seconds(elapsed, settings.max_countable_interval_seconds)
        previous = self._session_key()

        if previous and counted:
            added, total = self._credit(previous[0], previous[1], counted, previous_poll, now, resources)
            result.increment_seconds = added
            result.total_seconds = total
            result.resource_type, result.resource_id = previous
            if added:
                _log(
                    "SCREEN_TIME_USAGE",
                    resource_type=previous[0],
                    resource=previous[1],
                    increment_seconds=added,
                    total_seconds=total,
                )

        if previous != current:
            result.session_ended = self._end_session(
                now, reason="switch" if current else "background"
            )
            if current:
                result.session_started = self._start_session(
                    current[0], current[1], now, activity, resources=resources
                )
            if not result.increment_seconds and current:
                result.resource_type, result.resource_id = current
        return result

    def get_today_usage(
        self,
        resource_id,
        resource=None,
        now=None,
        grant=None,
        state_dir=None,
        resource_type=RESOURCE_TYPE_APP,
    ):
        now = now or datetime.now()
        resource_type = resource_type_of(resource, resource_type) if resource else resource_type
        resource_id = resource_id_of(resource) if resource and not resource_id else resource_id
        used = self._used_seconds(resource_type, resource_id, now)
        limit = 0
        if resource is not None:
            policy = resolve_policy(resource, now=now)
            limit = int(effective_daily_limit(policy, grant, now=now) or 0)
        remaining = max(0, limit - used) if limit else 0
        session_seconds = 0
        if self._session_key() == (resource_type, resource_id):
            session_seconds = self._session_duration
        else:
            session = self.store.get_open_session(resource_type, resource_id)
            if session:
                session_seconds = session.duration_seconds
        return TodayUsage(
            resource_type=resource_type,
            resource_id=resource_id,
            used_seconds=used,
            used_minutes=used // 60,
            limit_seconds=limit,
            remaining_seconds=remaining,
            currently_active=self._session_key() == (resource_type, resource_id),
            current_session_seconds=session_seconds,
        )

    def get_all_today_usage(self, resources=None, now=None, state_dir=None):
        now = now or datetime.now()
        items = listed_resources(resources)
        by_key = {(resource_type_of(item), resource_id_of(item)): item for item in items}
        rows = []
        seen = set()
        for item in self.store.get_all_daily(now.date().isoformat()):
            key = (item.resource_type, item.resource_id)
            seen.add(key)
            rows.append(
                self.get_today_usage(
                    item.resource_id,
                    resource=by_key.get(key),
                    now=now,
                    resource_type=item.resource_type,
                )
            )
        for resource in items:
            key = (resource_type_of(resource), resource_id_of(resource))
            if key in seen:
                continue
            rows.append(
                self.get_today_usage(
                    key[1],
                    resource=resource,
                    now=now,
                    resource_type=key[0],
                )
            )
        return rows

    def get_remaining_seconds(
        self,
        resource_id,
        resource=None,
        now=None,
        grant=None,
        state_dir=None,
        resource_type=RESOURCE_TYPE_APP,
    ):
        usage = self.get_today_usage(
            resource_id,
            resource=resource,
            now=now,
            grant=grant,
            state_dir=state_dir,
            resource_type=resource_type,
        )
        if not usage.limit_seconds:
            return None
        return usage.remaining_seconds

    def get_current_activity(self):
        if not self._session_resource_id:
            return None
        return {
            "resource_type": self._session_resource_type,
            "resource_id": self._session_resource_id,
            "identifier": self._session_identifier,
            "pid": self._session_pid,
            "session_start": format_timestamp(self._session_started_at),
            "current_session_seconds": self._session_duration,
        }

    def get_current_session(self, resource_id, resource_type=RESOURCE_TYPE_APP) -> Optional[SessionRecord]:
        if (
            self._session_key() == (resource_type, resource_id)
            and self._session_id is not None
        ):
            return SessionRecord(
                id=self._session_id,
                resource_type=resource_type,
                resource_id=resource_id,
                started_at=format_timestamp(self._session_started_at),
                ended_at=None,
                duration_seconds=self._session_duration,
                pid=self._session_pid,
                identifier=self._session_identifier,
            )
        return self.store.get_open_session(resource_type, resource_id)

    def snapshot(self, resource_id, now=None, state_dir=None, resource_type=RESOURCE_TYPE_APP) -> UsageSnapshot:
        now = now or datetime.now()
        used = self._used_seconds(resource_type, resource_id, now)
        active = self._session_key() == (resource_type, resource_id)
        return UsageSnapshot(
            resource_type=resource_type,
            resource_id=resource_id,
            date=now.date().isoformat(),
            total_active_seconds=used,
            current_session_seconds=self._session_duration if active else 0,
            current_session_start=format_timestamp(self._session_started_at) if active else None,
            last_seen_timestamp=format_timestamp(self._last_poll) if self._last_poll else None,
            is_currently_active=active,
        )

    def _session_key(self) -> Optional[ResourceKey]:
        if not self._session_resource_type or not self._session_resource_id:
            return None
        return (self._session_resource_type, self._session_resource_id)

    def _used_seconds(self, resource_type, resource_id, now):
        row = self.store.get_daily(now.date().isoformat(), resource_type, resource_id)
        if row is not None:
            return int(row.total_active_seconds)
        return 0

    def _credit(self, resource_type, resource_id, seconds, from_time, now, resources=None):
        """Add seconds to the day that contains the interval; split at local midnight."""
        if from_time is not None and from_time.date() != now.date():
            return self._credit_across_midnight(
                resource_type, resource_id, seconds, from_time, now, resources=resources
            )
        total = self.store.add_active_seconds(
            now.date().isoformat(), resource_type, resource_id, seconds, format_timestamp(now)
        )
        self._session_duration += seconds
        if self._session_id is not None:
            self.store.update_session(self._session_id, self._session_duration)
        return seconds, total

    def _credit_across_midnight(self, resource_type, resource_id, seconds, from_time, now, resources=None):
        midnight = datetime.combine(now.date(), time.min)
        if from_time.tzinfo is not None and midnight.tzinfo is None:
            midnight = midnight.replace(tzinfo=from_time.tzinfo)
        before = max(0, int(round((midnight - from_time).total_seconds())))
        after = max(0, int(seconds) - before)
        last_total = 0
        if before:
            last_total = self.store.add_active_seconds(
                from_time.date().isoformat(),
                resource_type,
                resource_id,
                before,
                format_timestamp(midnight),
            )
            self._session_duration += before
            keep_identifier = self._session_identifier
            keep_pid = self._session_pid
            self._end_session(midnight, reason="day_rollover")
            self._start_session(
                resource_type,
                resource_id,
                midnight,
                None,
                identifier=keep_identifier,
                pid=keep_pid,
                resources=resources,
            )
        if after:
            last_total = self.store.add_active_seconds(
                now.date().isoformat(),
                resource_type,
                resource_id,
                after,
                format_timestamp(now),
            )
            self._session_duration += after
            if self._session_id is not None:
                self.store.update_session(self._session_id, self._session_duration)
        elif resource_id and self._session_key() != (resource_type, resource_id):
            self._start_session(resource_type, resource_id, now, None, resources=resources)
        return before + after, last_total

    def _start_session(
        self,
        resource_type,
        resource_id,
        now,
        activity,
        identifier=None,
        pid=None,
        resources=None,
    ):
        if not identifier:
            if activity is not None and activity.identifier:
                identifier = str(activity.identifier).strip()
            elif self._session_identifier:
                identifier = self._session_identifier
            else:
                identifier = str(resource_id or "").strip()
        identifier = str(identifier or "").strip()
        if pid is None:
            pid = activity.pid if activity is not None else self._session_pid
        stamp = format_timestamp(now)
        self._session_id = self.store.start_session(
            resource_type,
            resource_id,
            stamp,
            pid=pid,
            identifier=identifier,
            created_at=stamp,
        )
        self._session_resource_type = resource_type
        self._session_resource_id = resource_id
        self._session_started_at = now
        self._session_duration = 0
        self._session_identifier = identifier
        self._session_pid = pid
        listed = find_listed_resource(resources, resource_type, resource_id)
        observed = ""
        if activity is not None:
            observed = activity.display_name
        display = (listed or {}).get("display_name") or default_display_name(
            resource_type, resource_id, observed
        )
        ident_type = IDENTIFIER_BUNDLE_ID
        if resource_type == RESOURCE_TYPE_APP and not is_bundle_id(resource_id):
            _, ident_type = app_resource_id(bundle_id="", process_name=resource_id)
        ensure_resource(
            self.store,
            resource_type,
            resource_id,
            display_name=display,
            identifier_type=ident_type,
            now=now,
        )
        _log(
            "SCREEN_TIME_SESSION_STARTED",
            resource_type=resource_type,
            resource=resource_id,
            identifier=identifier or None,
            pid=pid,
        )
        return True

    def _end_session(self, now, reason="switch"):
        if self._session_id is None:
            return False
        resource_id = self._session_resource_id
        duration = self._session_duration
        self.store.end_session(self._session_id, format_timestamp(now), duration)
        _log(
            "SCREEN_TIME_SESSION_ENDED",
            resource_type=self._session_resource_type,
            resource=resource_id,
            duration_seconds=duration,
            reason=reason,
        )
        self._clear_session()
        return True

    def _clear_session(self):
        self._session_id = None
        self._session_resource_type = None
        self._session_resource_id = None
        self._session_started_at = None
        self._session_duration = 0
        self._session_identifier = ""
        self._session_pid = None


def get_today_usage(tracker, resource_id, **kwargs):
    return tracker.get_today_usage(resource_id, **kwargs)


def get_all_today_usage(tracker, **kwargs):
    return tracker.get_all_today_usage(**kwargs)


def get_remaining_seconds(tracker, resource_id, **kwargs):
    return tracker.get_remaining_seconds(resource_id, **kwargs)


def get_current_activity(tracker):
    return tracker.get_current_activity()


def get_current_session(tracker, resource_id, resource_type=RESOURCE_TYPE_APP):
    return tracker.get_current_session(resource_id, resource_type=resource_type)


def _log(event, **fields):
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    logging.info("%s", " ".join(parts))
