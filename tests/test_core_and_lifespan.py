import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.main import app, lifespan


@pytest.mark.asyncio
async def test_security_utilities():
    # verify_password with wrong password
    hashed = get_password_hash("CorrectPass123!")
    assert verify_password("CorrectPass123!", hashed) is True
    assert verify_password("WrongPass123!", hashed) is False

    # create_access_token with expires_delta
    token = create_access_token({"sub": "test"}, expires_delta=timedelta(hours=1))
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    assert payload["sub"] == "test"
    assert "exp" in payload


@pytest.mark.asyncio
async def test_auth_dependencies_error_branches(
    client: AsyncClient, db_session: AsyncSession
):
    # 1. Token missing "sub"
    token_no_sub = jwt.encode(
        {"role": "player"}, settings.secret_key, algorithm=settings.algorithm
    )
    resp1 = await client.get(
        "/api/v1/tournaments", headers={"Authorization": f"Bearer {token_no_sub}"}
    )
    # create tournament requires admin auth
    resp1 = await client.post(
        "/api/v1/tournaments",
        json={"name": "T", "game": "G"},
        headers={"Authorization": f"Bearer {token_no_sub}"},
    )
    assert resp1.status_code == 401
    assert "sub manquant" in resp1.json()["detail"]

    # 2. Token with invalid non-UUID sub
    token_bad_sub = jwt.encode(
        {"sub": "not-a-valid-uuid"}, settings.secret_key, algorithm=settings.algorithm
    )
    resp2 = await client.post(
        "/api/v1/tournaments",
        json={"name": "T", "game": "G"},
        headers={"Authorization": f"Bearer {token_bad_sub}"},
    )
    assert resp2.status_code == 401
    assert "Impossible de valider les identifiants" in resp2.json()["detail"]

    # 3. Token with valid UUID sub but user does not exist in DB
    nonexistent_id = str(uuid.uuid4())
    token_no_user = jwt.encode(
        {"sub": nonexistent_id}, settings.secret_key, algorithm=settings.algorithm
    )
    resp3 = await client.post(
        "/api/v1/tournaments",
        json={"name": "T", "game": "G"},
        headers={"Authorization": f"Bearer {token_no_user}"},
    )
    assert resp3.status_code == 401
    assert "Utilisateur non trouvé" in resp3.json()["detail"]


@pytest.mark.asyncio
async def test_database_get_db_generator():
    # Mocking async_session_factory in app.core.database to test get_db()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    class MockSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.core.database.async_session_factory", MockSessionFactory()):
        # Normal path
        gen = get_db()
        sess = await anext(gen)
        assert sess == mock_session
        with pytest.raises(StopAsyncIteration):
            await anext(gen)
        mock_session.commit.assert_awaited_once()

        # Exception path
        gen2 = get_db()
        await anext(gen2)
        with pytest.raises(ValueError):
            await gen2.athrow(ValueError("Test error"))
        mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_database_url_conversion():
    from app.core.database import normalize_database_url

    res1 = normalize_database_url("postgresql://user:pass@localhost/db")
    assert res1.startswith("postgresql+asyncpg://")

    res2 = normalize_database_url("postgres://user:pass@localhost/db")
    assert res2.startswith("postgresql+asyncpg://")

    res3 = normalize_database_url("sqlite+aiosqlite:///:memory:")
    assert res3 == "sqlite+aiosqlite:///:memory:"


@pytest.mark.asyncio
async def test_main_lifespan():
    from unittest.mock import MagicMock

    # 1. Normal seeding branch
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add_all = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    class MockSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.main.async_session_factory", MockSessionFactory()):
        async with lifespan(app):
            pass
        mock_session.commit.assert_awaited_once()

    # 2. Already seeded branch (scalar_one_or_none returns a user)
    mock_session_seeded = AsyncMock(spec=AsyncSession)
    mock_result_seeded = MagicMock()
    mock_result_seeded.scalar_one_or_none.return_value = MagicMock()
    mock_session_seeded.execute = AsyncMock(return_value=mock_result_seeded)
    mock_session_seeded.commit = AsyncMock()

    class SeededSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return mock_session_seeded

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.main.async_session_factory", SeededSessionFactory()):
        async with lifespan(app):
            pass
        mock_session_seeded.commit.assert_not_awaited()

    # 3. Lifespan exception branch
    mock_session_fail = AsyncMock(spec=AsyncSession)
    mock_session_fail.execute = AsyncMock(side_effect=RuntimeError("DB error"))
    mock_session_fail.rollback = AsyncMock()

    class FailingSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return mock_session_fail

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("app.main.async_session_factory", FailingSessionFactory()):
        async with lifespan(app):
            pass
        mock_session_fail.rollback.assert_awaited_once()
