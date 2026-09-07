from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config import settings

# Small pool (1-2 per container) + pre-ping so a connection isn't reused stale
# after Neon compute scales to zero. (Neon serverless guidance.)
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=2,
    max_overflow=0,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    """FastAPI dependency: one fresh AsyncSession per request."""
    async with SessionLocal() as session:
        yield session
