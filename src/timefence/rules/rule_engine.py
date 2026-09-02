from datetime import datetime

from ..grants import load_grant
from ..policy import due_warnings, evaluate, resolve_policy, resource_label


class RuleEngine:
    """Policy decisions for a resource. Does not detect activity or enforce blocks."""

    def evaluate(self, resource, usage_state, current_time=None, grant=None):
        now = current_time or datetime.now()
        policy = resolve_policy(resource, now=now)
        return policy, evaluate(policy, usage_state, now=now, grant=grant)

    def due_warnings(self, name, resource, usage_state, current_time=None, window=None, grant=None):
        now = current_time or datetime.now()
        policy = resolve_policy(resource, now=now)
        label = resource_label(name, resource)
        return due_warnings(policy, usage_state, window=window, label=label, grant=grant, now=now)

    def load_grant(self, state_dir, resource_id, current_time=None):
        return load_grant(state_dir, resource_id, now=current_time)
