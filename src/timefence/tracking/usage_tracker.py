import logging
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional

from ..activity.matching import find_resource_for_activity
from ..grants import effective_daily_limit
from ..models.activity import KIND_APP, Observation
from ..models.usage import SessionRecord, TodayUsage, UsageSnapshot
from ..policy import resolve_policy
from .usage_store import UsageStore

MAX_COUNTABLE_INTERVAL_SECONDS = 30
DEFAULT_IDLE_THRESHOLD_SECONDS = 120


def format_timestamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return value.replace(microsecond=0).isoformat()


def countable_seconds(elapsed, max_countable=MAX_COUNTABLE_INTERVAL_SECONDS):
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
    resource_id: Optional[str] = None
    increment_seconds: int = 0
    total_seconds: int = 0
    session_started: bool = False
    session_ended: bool = False
    idle: bool = False
    interrupted: bool = False
    bundle_id: str = ""


class UsageTracker:
    """Turns activity observations into daily usage and sessions. Does not enforce policy.

    The monitor reports facts (who is in front, idle seconds). This class owns
    the accounting rules: elapsed time, max gap, idle, one resource at a time,
    and day split at midnight.
    """

    def __init__(self, store: UsageStore):
        self.store = store
        self._last_poll = None
        self._session_id = None
        self._session_resource_id = None
        self._session_started_at = None
        self._session_duration = 0
        self._session_kind = KIND_APP
        self._session_identifier = ""
        self._was_idle = False

    def close_orphaned_sessions(self, now=None):
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
        """Turn one monitor snapshot into session/usage updates.

        Rules of thumb:
        - Elapsed time is (now - previous poll), never the configured interval.
        - Gaps larger than max_countable_interval_seconds are sleep/stall:
          end the session, do not credit the gap.
        - Idle/lock: do not credit this interval; end the session.
        - Credit the resource that was in front *during* the interval (the
          previous session), then switch session to whoever is in front now.
          A Roblox → Chrome poll therefore adds those seconds to Roblox.
        - First poll after start only opens a session (elapsed is 0).
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

        # Idle/lock: do not resolve a resource, so nothing can start a session.
        activity = None if (idle or locked) else observation.resolved_activity()
        match = find_resource_for_activity(resources, activity) if activity else None
        current_id = match[0] if match else None
        bundle_id = ""
        if activity is not None:
            bundle_id = activity.identifier
        elif observation.frontmost is not None:
            bundle_id = observation.frontmost.bundle_id

        result = TickResult(
            resource_id=current_id,
            idle=idle,
            interrupted=interrupted,
            bundle_id=bundle_id,
        )

        if idle and not self._was_idle:
            _log("SCREEN_TIME_IDLE", idle_seconds=int(observation.idle_seconds))
        self._was_idle = idle or locked

        if interrupted:
            # Sleep, debugger pause, or a stalled poll: drop the gap entirely.
            result.session_ended = self._end_session(now, reason="interrupted")
            if current_id:
                result.session_started = self._start_session(current_id, now, activity)
            return result

        if idle or locked:
            result.session_ended = self._end_session(now, reason="locked" if locked else "idle")
            return result

        counted = countable_seconds(elapsed, settings.max_countable_interval_seconds)
        previous_id = self._session_resource_id

        if previous_id and counted:
            added, total = self._credit(previous_id, counted, previous_poll, now)
            result.increment_seconds = added
            result.total_seconds = total
            # Keep resource_id as the app that consumed this interval so the
            # controller dual-writes JSON usage to the right resource even if
            # we switch away on this same poll.
            result.resource_id = previous_id
            if added:
                _log(
                    "SCREEN_TIME_USAGE",
                    resource=previous_id,
                    increment_seconds=added,
                    total_seconds=total,
                )

        if previous_id != current_id:
            result.session_ended = self._end_session(
                now, reason="switch" if current_id else "background"
            )
            if current_id:
                result.session_started = self._start_session(current_id, now, activity)
            if not result.increment_seconds:
                result.resource_id = current_id
        return result

    def get_today_usage(self, resource_id, resource=None, now=None, grant=None, state_dir=None):
        now = now or datetime.now()
        used = self._used_seconds(resource_id, now, state_dir=state_dir)
        limit = 0
        if resource is not None:
            policy = resolve_policy(resource, now=now)
            limit = int(effective_daily_limit(policy, grant, now=now) or 0)
        remaining = max(0, limit - used) if limit else 0
        session_seconds = 0
        if self._session_resource_id == resource_id:
            session_seconds = self._session_duration
        else:
            session = self.store.get_open_session(resource_id)
            if session:
                session_seconds = session.duration_seconds
        return TodayUsage(
            resource_id=resource_id,
            used_seconds=used,
            used_minutes=used // 60,
            limit_seconds=limit,
            remaining_seconds=remaining,
            currently_active=self._session_resource_id == resource_id,
            current_session_seconds=session_seconds,
        )

    def get_all_today_usage(self, resources=None, now=None, state_dir=None):
        now = now or datetime.now()
        resources = resources or {}
        rows = []
        seen = set()
        for item in self.store.get_all_daily(now.date().isoformat()):
            seen.add(item.resource_id)
            rows.append(
                self.get_today_usage(
                    item.resource_id,
                    resource=resources.get(item.resource_id),
                    now=now,
                    state_dir=state_dir,
                )
            )
        for name in resources:
            if name in seen:
                continue
            rows.append(
                self.get_today_usage(name, resource=resources.get(name), now=now, state_dir=state_dir)
            )
        return rows

    def get_remaining_seconds(self, resource_id, resource=None, now=None, grant=None, state_dir=None):
        usage = self.get_today_usage(
            resource_id, resource=resource, now=now, grant=grant, state_dir=state_dir
        )
        if not usage.limit_seconds:
            return None
        return usage.remaining_seconds

    def get_current_activity(self):
        if not self._session_resource_id:
            return None
        return {
            "resource_id": self._session_resource_id,
            "activity_kind": self._session_kind,
            "identifier": self._session_identifier,
            "session_start": format_timestamp(self._session_started_at),
            "current_session_seconds": self._session_duration,
        }

    def get_current_session(self, resource_id) -> Optional[SessionRecord]:
        if self._session_resource_id == resource_id and self._session_id is not None:
            return SessionRecord(
                id=self._session_id,
                resource_id=resource_id,
                started_at=format_timestamp(self._session_started_at),
                ended_at=None,
                duration_seconds=self._session_duration,
                activity_kind=self._session_kind,
                identifier=self._session_identifier,
            )
        return self.store.get_open_session(resource_id)

    def snapshot(self, resource_id, now=None, state_dir=None) -> UsageSnapshot:
        now = now or datetime.now()
        used = self._used_seconds(resource_id, now, state_dir=state_dir)
        active = self._session_resource_id == resource_id
        return UsageSnapshot(
            resource_id=resource_id,
            date=now.date().isoformat(),
            total_active_seconds=used,
            current_session_seconds=self._session_duration if active else 0,
            current_session_start=format_timestamp(self._session_started_at) if active else None,
            last_seen_timestamp=format_timestamp(self._last_poll) if self._last_poll else None,
            is_currently_active=active,
        )

    def _used_seconds(self, resource_id, now, state_dir=None):
        row = self.store.get_daily(now.date().isoformat(), resource_id)
        if row is not None:
            return int(row.total_active_seconds)
        if state_dir is not None:
            from ..usage import get_usage

            return int(get_usage(state_dir, resource_id, now=now) or 0)
        return 0

    def _credit(self, resource_id, seconds, from_time, now):
        if from_time is not None and from_time.date() != now.date():
            return self._credit_across_midnight(resource_id, seconds, from_time, now)
        total = self.store.add_active_seconds(
            now.date().isoformat(), resource_id, seconds, format_timestamp(now)
        )
        self._session_duration += seconds
        if self._session_id is not None:
            self.store.update_session(self._session_id, self._session_duration)
        return seconds, total

    def _credit_across_midnight(self, resource_id, seconds, from_time, now):
        midnight = datetime.combine(now.date(), time.min)
        if from_time.tzinfo is not None and midnight.tzinfo is None:
            midnight = midnight.replace(tzinfo=from_time.tzinfo)
        before = max(0, int(round((midnight - from_time).total_seconds())))
        after = max(0, int(seconds) - before)
        last_total = 0
        if before:
            last_total = self.store.add_active_seconds(
                from_time.date().isoformat(),
                resource_id,
                before,
                format_timestamp(midnight),
            )
            self._session_duration += before
            self._end_session(midnight, reason="day_rollover")
            self._start_session(resource_id, midnight, None)
        if after:
            last_total = self.store.add_active_seconds(
                now.date().isoformat(),
                resource_id,
                after,
                format_timestamp(now),
            )
            self._session_duration += after
            if self._session_id is not None:
                self.store.update_session(self._session_id, self._session_duration)
        elif resource_id and self._session_resource_id != resource_id:
            self._start_session(resource_id, now, None)
        return before + after, last_total

    def _start_session(self, resource_id, now, activity):
        kind = activity.kind if activity is not None else KIND_APP
        identifier = activity.identifier if activity is not None else ""
        self._session_id = self.store.start_session(
            resource_id,
            format_timestamp(now),
            activity_kind=kind,
            identifier=identifier,
        )
        self._session_resource_id = resource_id
        self._session_started_at = now
        self._session_duration = 0
        self._session_kind = kind
        self._session_identifier = identifier
        _log("SCREEN_TIME_SESSION_STARTED", resource=resource_id, bundle_id=identifier or None)
        return True

    def _end_session(self, now, reason="switch"):
        if self._session_id is None:
            return False
        resource_id = self._session_resource_id
        duration = self._session_duration
        self.store.end_session(self._session_id, format_timestamp(now), duration)
        _log(
            "SCREEN_TIME_SESSION_ENDED",
            resource=resource_id,
            duration_seconds=duration,
            reason=reason,
        )
        self._clear_session()
        return True

    def _clear_session(self):
        self._session_id = None
        self._session_resource_id = None
        self._session_started_at = None
        self._session_duration = 0
        self._session_kind = KIND_APP
        self._session_identifier = ""


def get_today_usage(tracker, resource_id, **kwargs):
    return tracker.get_today_usage(resource_id, **kwargs)


def get_all_today_usage(tracker, **kwargs):
    return tracker.get_all_today_usage(**kwargs)


def get_remaining_seconds(tracker, resource_id, **kwargs):
    return tracker.get_remaining_seconds(resource_id, **kwargs)


def get_current_activity(tracker):
    return tracker.get_current_activity()


def get_current_session(tracker, resource_id):
    return tracker.get_current_session(resource_id)


def _log(event, **fields):
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")
    logging.info("%s", " ".join(parts))
