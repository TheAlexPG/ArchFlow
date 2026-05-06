"""Top-level pytest conftest.

Two responsibilities, both run BEFORE backend/tests/conftest.py and BEFORE
any `app.*` imports so the test session sees the right env from the start.

1. sys.path bootstrap
   ---------------------
   Prepend ``backend/`` so the eval suite's ``from evals.lib.judge import ...``
   resolves under uv's virtual workspace (uv keeps the project as
   ``source = virtual = "."`` and never copies it into site-packages).

2. Test-DB safety + auto-bootstrap
   ---------------------------------
   The pytest fixtures TRUNCATE production tables (``users``, ``workspaces``,
   ``diagrams``, …) — running tests against the dev database wipes real
   accounts in seconds. To make that physically impossible, we:

     * Read ``DATABASE_URL`` from the environment.
     * If the DB name does not end in ``_test``, derive a sibling DB
       ``<name>_test`` (e.g. ``archflow`` → ``archflow_test``) and override
       ``os.environ["DATABASE_URL"]`` (and ``DATABASE_URL_SYNC`` if set).
     * Connect to the Postgres admin DB (``postgres``), create the
       ``_test`` sibling if missing.
     * Run ``alembic upgrade head`` against the test DB.

   Effect: ``pytest tests/`` always lands on ``archflow_test``. The dev
   ``archflow`` DB is never touched. Prod URLs (which presumably do not
   end in ``_test``) get the same treatment locally — but no one runs
   pytest against prod, and even if they did, only ``<prod>_test`` would
   be touched, never the real DB.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

# ── 1. sys.path ──────────────────────────────────────────────────────────────

_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


# ── 2. Test-DB bootstrap ─────────────────────────────────────────────────────


def _swap_db_in_url(url: str, new_db: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{new_db}"))


async def _create_db_if_missing(async_url: str, target_db: str) -> None:
    """Connect to the server's `postgres` admin DB and CREATE DATABASE if
    needed. Uses asyncpg directly so we don't pull SQLAlchemy in here.
    """
    import asyncpg

    parsed = urlparse(async_url)
    # asyncpg expects ``postgresql://``; strip any ``+asyncpg`` driver tag.
    admin_scheme = parsed.scheme.replace("+asyncpg", "")
    admin_dsn = urlunparse(parsed._replace(scheme=admin_scheme, path="/postgres"))

    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", target_db
        )
        if not exists:
            # CREATE DATABASE can't be parameterised; quote the identifier.
            quoted = '"' + target_db.replace('"', '""') + '"'
            await conn.execute(f"CREATE DATABASE {quoted}")
    finally:
        await conn.close()


def _alembic_upgrade(target_url: str) -> None:
    """Run ``alembic upgrade head`` against the given async URL."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", target_url)
    command.upgrade(cfg, "head")


def _bootstrap_test_database() -> None:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        # No env URL — fall back to whatever app.core.config defaults to,
        # which is `localhost:5432/archflow`. Manufacture one so we still
        # land on `_test`.
        raw = "postgresql+asyncpg://archflow:archflow@localhost:5432/archflow"

    parsed = urlparse(raw)
    db_name = parsed.path.lstrip("/")
    if not db_name:
        raise RuntimeError(
            f"DATABASE_URL has no database name: {raw}. "
            "Cannot derive a test DB safely."
        )

    if db_name.endswith("_test"):
        target_db = db_name
        target_url = raw
    else:
        target_db = f"{db_name}_test"
        target_url = _swap_db_in_url(raw, target_db)
        os.environ["DATABASE_URL"] = target_url
        sync_raw = os.environ.get("DATABASE_URL_SYNC")
        if sync_raw:
            os.environ["DATABASE_URL_SYNC"] = _swap_db_in_url(sync_raw, target_db)

    asyncio.run(_create_db_if_missing(target_url, target_db))
    _alembic_upgrade(target_url)


# Run once on conftest load. Any failure here aborts the test session
# loudly — that's the point: better a crash than a silent wipe of dev data.
_bootstrap_test_database()
