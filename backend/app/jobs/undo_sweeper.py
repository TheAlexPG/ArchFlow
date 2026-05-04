"""Hard-delete undo entries older than the retention window.

Schedule via cron / cloud scheduler — once daily is enough. The retention
cutoff itself lives in `undo_service.RETENTION_DAYS`.
"""
import asyncio

from app.core.database import async_session
from app.services import undo_service


async def main() -> None:
    async with async_session() as db:
        deleted = await undo_service.sweep_old_entries(db)
        print(f"undo_sweeper: deleted {deleted} entries")


if __name__ == "__main__":
    asyncio.run(main())
