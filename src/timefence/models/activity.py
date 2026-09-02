from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Activity.kind values. The monitor currently emits APP only. WEBSITE is for a
# future extension posting a URL into UsageTracker; MEDIA is reserved.
KIND_APP = "app"
KIND_WEBSITE = "website"
KIND_MEDIA = "media"


@dataclass(frozen=True)
class FrontmostApp:
    """GUI app currently in front. bundle_id is what we match in rules.json."""

    app_name: str
    bundle_id: str
    pid: int

    def to_dict(self):
        return {
            "app_name": self.app_name,
            "bundle_id": self.bundle_id,
            "pid": self.pid,
        }


@dataclass(frozen=True)
class Activity:
    """One unit of observed activity. Apps use bundle ID; websites can later use a domain."""

    kind: str
    identifier: str
    display_name: str = ""
    pid: Optional[int] = None

    @classmethod
    def from_frontmost(cls, app: FrontmostApp):
        return cls(
            kind=KIND_APP,
            identifier=app.bundle_id,
            display_name=app.app_name,
            pid=app.pid,
        )


@dataclass(frozen=True)
class Observation:
    """One monitor snapshot. UsageTracker reads this; it does not mutate it.

    Set `activity` directly to inject a website/media event without a frontmost
    app (tests and a future browser extension). Otherwise `resolved_activity()`
    builds an APP Activity from `frontmost.bundle_id`.
    """

    timestamp: datetime
    idle_seconds: float
    screen_locked: bool = False
    frontmost: Optional[FrontmostApp] = None
    activity: Optional[Activity] = field(default=None)

    def resolved_activity(self) -> Optional[Activity]:
        if self.activity is not None:
            return self.activity
        if self.frontmost and self.frontmost.bundle_id:
            return Activity.from_frontmost(self.frontmost)
        return None
