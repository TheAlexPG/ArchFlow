import contextlib
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with async_session() as session:
        try:
            yield session
        except BaseException:
            # SSE endpoints get cancelled when the frontend aborts (tab close,
            # navigation, network blip). uvicorn raises asyncio.CancelledError
            # which is a BaseException — not Exception — so a plain
            # `except Exception` would miss it and the noisy "Exception
            # terminating connection" + "Exception in ASGI application"
            # tracebacks would land in prod logs on every disconnect.
            #
            # Catch BaseException, attempt a best-effort rollback, then
            # re-raise so the framework still treats the request as cancelled.
            # The rollback itself can also raise CancelledError if the scope
            # is already torn down — suppress that too, SQLAlchemy still
            # returns the connection to the pool on its own.
            with contextlib.suppress(BaseException):
                await session.rollback()
            raise
        else:
            await session.commit()
