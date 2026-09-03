import logging


class EnforcementService:
    """Quit/close a resource. Does not decide whether a block is required.

    The controller evaluates policy, then calls this. Keeping the two separate
    lets tests block without hitting `pkill`, and lets a later MDM backend
    replace this class without touching the loop.
    """

    def __init__(self, module_for):
        self._module_for = module_for

    def enforce(self, resource, name=None):
        mod = self._module_for(resource)
        if mod is None:
            logging.warning("No enforcement module for %s/%s", resource.get("resource_type"), resource.get("resource_id"))
            return False
        mod.enforce(resource)
        return True
