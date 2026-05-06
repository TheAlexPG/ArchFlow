"""
Agent-specific exception hierarchy.
All agent runtime errors derive from AgentError so callers can catch broadly.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base class for all agent runtime errors."""


class ToolDenied(AgentError):  # noqa: N818
    """Raised when a tool call is denied by ACL or policy checks."""


class BudgetExhausted(AgentError):  # noqa: N818
    """Raised when the agent's USD budget limit has been reached."""


class ContextOverflow(AgentError):  # noqa: N818
    """Raised when context cannot be compacted further to fit the context window."""


class TurnLimitReached(AgentError):  # noqa: N818
    """Raised when the agent exceeds its maximum turn count after health-check escalation."""
