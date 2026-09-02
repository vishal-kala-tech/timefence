"""macOS process lookup/quit. Thin wrapper around the activity-monitor helpers."""

from typing import Dict, Optional

from ...models.activity import FrontmostApp
from ..base import ProcessController
from .activity_monitor import frontmost_application, running_bundle_ids, terminate_bundle_ids


class MacOSProcessController(ProcessController):
    def frontmost_application(self) -> Optional[FrontmostApp]:
        return frontmost_application()

    def running_app_ids(self) -> Dict[str, int]:
        return running_bundle_ids()

    def terminate_app_ids(self, app_ids) -> None:
        terminate_bundle_ids(app_ids)
