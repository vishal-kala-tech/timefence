import logging


class EnforcementService:
    """Runs resource-module enforcement. Does not decide whether a block is required."""

    def __init__(self, module_for):
        self._module_for = module_for

    def enforce(self, name, resource):
        mod = self._module_for(name, resource)
        if mod is None:
            logging.warning("No enforcement module for %s", name)
            return False
        mod.enforce(resource)
        return True
