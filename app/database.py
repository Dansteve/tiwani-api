from supabase import create_client, Client
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

# Initialize Supabase clients for auth and direct table access
supabase_client: Client = create_client(
    supabase_url=settings.SUPABASE_URL,
    supabase_key=settings.SUPABASE_KEY
)

supabase_admin: Client = create_client(
    supabase_url=settings.SUPABASE_URL,
    supabase_key=settings.SUPABASE_SERVICE_ROLE_KEY
)

if not settings.DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set in .env for SQLAlchemy database access")

engine = create_async_engine(
    settings.DATABASE_URL,
    future=True,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
