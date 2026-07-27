from collections.abc import AsyncIterator
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()


def asyncpg_url(raw_url: str):
    """Convert the Prisma/Supabase connection URL into an asyncpg-safe URL.

    Prisma accepts `pgbouncer=true` and `connection_limit`; asyncpg forwards
    unknown query parameters to ``asyncpg.connect`` and crashes on them.
    """
    url = make_url(raw_url)
    url = url.set(drivername="postgresql+asyncpg")
    return url.difference_update_query(["pgbouncer", "connection_limit"])


_raw_database_url = settings.database_url
_uses_pgbouncer = make_url(_raw_database_url).query.get("pgbouncer", "").lower() == "true"
engine = create_async_engine(
    asyncpg_url(_raw_database_url),
    pool_pre_ping=True,
    # Supabase transaction pooling may hand us a physical PostgreSQL connection
    # that already contains asyncpg's numeric statement name.  SQLAlchemy's
    # documented PgBouncer workaround is a unique name per prepared statement
    # plus no client-side connection pool/cache.
    poolclass=NullPool if _uses_pgbouncer else None,
    connect_args=(
        {
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        }
        if _uses_pgbouncer
        else {}
    ),
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def get_redis() -> Redis:
    return redis_client
