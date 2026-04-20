"""Role hierarchy + permission checks.

Roles (high → low):
    owner    workspace_owner, full control including delete workspace
    admin    manage members, teams, diagrams, content
    editor   create/edit/delete model entities
    reviewer read + comment, open drafts, can't apply them
    viewer   read-only

`has_role(user_role, minimum)` is a monotonic check: owner satisfies every
minimum, admin satisfies everything except owner, and so on.
"""
from app.models.workspace import Role

# Lowest-to-highest ordering. Index into this list = numeric rank.
_ORDER = [Role.VIEWER, Role.REVIEWER, Role.EDITOR, Role.ADMIN, Role.OWNER]


def role_rank(role: Role) -> int:
    return _ORDER.index(role)


def has_role(user_role: Role, minimum: Role) -> bool:
    return role_rank(user_role) >= role_rank(minimum)
