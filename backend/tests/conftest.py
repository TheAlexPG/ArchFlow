import json
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.database import async_session
from app.main import app
from app.models.diagram import Diagram, DiagramType
from app.models.user import User
from app.models.workspace import Organization, Role, Workspace, WorkspaceMember


# Share one event loop across the whole test session so the asyncpg pool
# survives between tests. pytest-asyncio's default "new loop per test" would
# close the loop while DB connections are still open.
@pytest.fixture(scope="session")
def event_loop_policy():
    import asyncio

    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# DB fixtures for service-level tests
# ---------------------------------------------------------------------------
# These give a session and pre-baked user/workspace/diagram that hang together
# (FKs satisfied) so service tests can write rows without going through the
# HTTP layer. Each `db` fixture truncates the tables it touches at start so
# tests don't leak rows into each other.

# Tables that service tests are allowed to write to. Truncated CASCADE so any
# dependent rows go too. Order doesn't matter with CASCADE.
_SERVICE_TEST_TABLES = (
    "undo_entries",
    "draft_diagrams",
    "drafts",
    "diagram_objects",
    "diagrams",
    "workspace_members",
    "workspaces",
    "organizations",
    "users",
)

_TECHNOLOGY_SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "technologies.json"
_EXTRA_BUILTIN_PROTOCOLS = (
    {
        "slug": "mcp",
        "name": "MCP",
        "iconify_name": "mdi:message-processing-outline",
        "category": "protocol",
        "color": "#D97757",
        "aliases": ["model-context-protocol", "model context protocol"],
    },
    {
        "slug": "a2a",
        "name": "A2A",
        "iconify_name": "mdi:account-switch-outline",
        "category": "protocol",
        "color": "#6366F1",
        "aliases": ["agent-to-agent", "agent to agent"],
    },
)


async def _restore_builtin_technologies(session):
    """Restore built-in technology rows after workspace truncation.

    TRUNCATE workspaces CASCADE removes workspace-scoped technologies and, in
    PostgreSQL, also truncates the whole referencing technologies table. The
    migration seed does not rerun between tests, so put the built-ins back.
    """
    rows = json.loads(_TECHNOLOGY_SEED_PATH.read_text()) + list(_EXTRA_BUILTIN_PROTOCOLS)
    insert_sql = text(
        """
        INSERT INTO technologies
            (id, workspace_id, slug, name, iconify_name, category, color, aliases)
        VALUES
            (gen_random_uuid(), NULL, :slug, :name, :iconify_name,
             CAST(:category AS tech_category), :color, :aliases)
        ON CONFLICT (slug) WHERE workspace_id IS NULL
        DO UPDATE SET
            name = EXCLUDED.name,
            iconify_name = EXCLUDED.iconify_name,
            category = EXCLUDED.category,
            color = EXCLUDED.color,
            aliases = EXCLUDED.aliases,
            updated_at = now()
        """
    )
    for row in rows:
        await session.execute(
            insert_sql,
            {
                "slug": row["slug"],
                "name": row["name"],
                "iconify_name": row["iconify_name"],
                "category": row["category"].upper(),
                "color": row.get("color"),
                "aliases": row.get("aliases") or None,
            },
        )


@pytest.fixture
async def db():
    """AsyncSession for direct service tests. Truncates relevant tables on
    entry so each test starts clean."""
    async with async_session() as session:
        await session.execute(
            text(
                "TRUNCATE "
                + ", ".join(_SERVICE_TEST_TABLES)
                + " RESTART IDENTITY CASCADE"
            )
        )
        await _restore_builtin_technologies(session)
        await session.commit()
        try:
            yield session
        finally:
            await session.rollback()


async def _make_user(session, *, name: str = "Test User") -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        email=f"u-{suffix}@example.com",
        name=name,
        password_hash="x",
        auth_provider="local",
    )
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
async def user(db) -> User:
    u = await _make_user(db, name="Primary")
    await db.flush()
    return u


@pytest.fixture
async def user_other(db) -> User:
    u = await _make_user(db, name="Other")
    await db.flush()
    return u


@pytest.fixture
async def workspace(db, user) -> Workspace:
    org = Organization(name="Test Org", slug=f"org-{uuid.uuid4().hex[:8]}")
    db.add(org)
    await db.flush()
    ws = Workspace(org_id=org.id, name="Test WS", slug=f"ws-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=Role.OWNER))
    await db.flush()
    return ws


@pytest.fixture
async def diagram(db, workspace) -> Diagram:
    d = Diagram(
        name="Test Diagram",
        type=DiagramType.CONTAINER,
        workspace_id=workspace.id,
    )
    db.add(d)
    await db.flush()
    return d
