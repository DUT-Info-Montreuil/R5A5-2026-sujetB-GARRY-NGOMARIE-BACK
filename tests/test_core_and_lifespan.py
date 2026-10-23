from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db


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
