"""Railway Cron entry (second service, same repo). Runs ~every 5 min."""
import asyncio

from db.session import SessionLocal, engine
from sweep import run_sweep


async def _main() -> None:
    async with SessionLocal() as db:
        result = await run_sweep(db)
    await engine.dispose()
    print(f"sweep: holds_expired={result['holds_expired']} "
          f"followups_sent={result['followups_sent']}")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()