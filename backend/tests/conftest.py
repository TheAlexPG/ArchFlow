import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


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
