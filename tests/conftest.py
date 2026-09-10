import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models
from app.core.database import Base, get_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.entities import User

# Base SQLite en mémoire pour tests isolés rapides
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@pytest_asyncio.fixture
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    admin = User(
        id=uuid.uuid4(),
        username="admin_test",
        email="admin@tournament.test",
        hashed_password=get_password_hash("AdminPass123!"),
        global_role="admin",
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


@pytest_asyncio.fixture
async def player_user(db_session: AsyncSession) -> User:
    player = User(
        id=uuid.uuid4(),
        username="player_test",
        email="player@tournament.test",
        hashed_password=get_password_hash("PlayerPass123!"),
        global_role="player",
    )
    db_session.add(player)
    await db_session.commit()
    await db_session.refresh(player)
    return player


@pytest.fixture
def admin_headers(admin_user: User) -> dict[str, str]:
    token = create_access_token(
        data={
            "sub": str(admin_user.id),
            "username": admin_user.username,
            "role": "admin",
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def player_headers(player_user: User) -> dict[str, str]:
    token = create_access_token(
        data={
            "sub": str(player_user.id),
            "username": player_user.username,
            "role": "player",
        }
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def open_tournament(db_session: AsyncSession, admin_user: User):
    from app.models.entities import Tournament

    t = Tournament(
        id=uuid.uuid4(),
        name="Tournament Open",
        game="Valorant",
        status="registration_open",
        created_by=admin_user.id,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t
