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
from app.api.v1.diagram_access import router as diagram_access_router
from app.api.v1.invites import router as invites_router
from app.api.v1.members import router as members_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.oauth_stub import router as oauth_router
from app.api.v1.teams import router as teams_router
from app.api.v1.packs import router as packs_router
from app.api.v1.versions import router as versions_router
from app.api.v1.websocket import router as websocket_router
from app.api.v1.workspaces import router as workspaces_router
from app.core.config import settings
from app.core.database import engine
from app.realtime.manager import manager as ws_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis subscriber starts lazily on first WS join too, but kicking it
    # off at app boot means REST endpoints that publish events don't
    # race the subscriber's first iteration.
    await ws_manager.start()
    yield
    await ws_manager.stop()
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
    app.include_router(workspaces_router, prefix="/api/v1")
    app.include_router(members_router, prefix="/api/v1")
    app.include_router(teams_router, prefix="/api/v1")
    app.include_router(packs_router, prefix="/api/v1")
    app.include_router(diagram_access_router, prefix="/api/v1")
    app.include_router(oauth_router, prefix="/api/v1")
    app.include_router(invites_router, prefix="/api/v1")
    app.include_router(versions_router, prefix="/api/v1")
    app.include_router(websocket_router, prefix="/api/v1")
    app.include_router(notifications_router, prefix="/api/v1")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
