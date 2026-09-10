import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


def normalize_database_url(url: str) -> str:
    """Convert postgresql:// or postgres:// to postgresql+asyncpg:// if needed"""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


DATABASE_URL = normalize_database_url(
    os.getenv(
        "DATABASE_URL",
        settings.database_url,
    )
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles SQLAlchemy"""


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Dépendance FastAPI pour obtenir une session de base de données asynchrone"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
