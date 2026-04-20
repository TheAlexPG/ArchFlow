from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.activity import router as activity_router
from app.api.v1.api_keys import router as api_keys_router
from app.api.v1.auth import router as auth_router
from app.api.v1.comments import router as comments_router
from app.api.v1.connections import router as connections_router
from app.api.v1.diagrams import router as diagrams_router
from app.api.v1.drafts import router as drafts_router
from app.api.v1.export import router as export_router
from app.api.v1.flows import diagrams_router as flow_diagrams_router
from app.api.v1.flows import router as flows_router
from app.api.v1.objects import router as objects_router
from app.api.v1.webhooks import router as webhooks_router
from app.core.config import settings
from app.core.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ArchFlow API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(objects_router, prefix="/api/v1")
    app.include_router(connections_router, prefix="/api/v1")
    app.include_router(diagrams_router, prefix="/api/v1")
    app.include_router(flow_diagrams_router, prefix="/api/v1")
    app.include_router(flows_router, prefix="/api/v1")
    app.include_router(comments_router, prefix="/api/v1")
    app.include_router(activity_router, prefix="/api/v1")
    app.include_router(drafts_router, prefix="/api/v1")
    app.include_router(export_router, prefix="/api/v1")
    app.include_router(api_keys_router, prefix="/api/v1")
    app.include_router(webhooks_router, prefix="/api/v1")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
