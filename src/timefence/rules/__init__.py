"""Policy facade. Prefer `policy.evaluate` for new code; this wraps it."""

from .rule_engine import RuleEngine

__all__ = ["RuleEngine"]
