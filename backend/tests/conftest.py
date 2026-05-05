import uuid

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
