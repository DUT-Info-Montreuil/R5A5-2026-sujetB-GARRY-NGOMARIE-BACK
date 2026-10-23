"""Functional tests of password accounts (register, login, then the same session)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import User, UserSession
from tests.helpers import TRUSTED_ORIGIN

ORIGIN = {"Origin": TRUSTED_ORIGIN}
ALICE = {"username": "alice", "email": "Alice@Example.com", "password": "correct-horse"}


def _session_cookie(resp) -> str:
    return next(
        c for c in resp.headers.get_list("set-cookie") if c.startswith("session=")
    )


async def _register(client: AsyncClient, body: dict = ALICE):
    return await client.post("/api/v1/auth/register", json=body, headers=ORIGIN)


@pytest.mark.asyncio
async def test_register_creates_player_and_opens_session(
    client: AsyncClient, db_session: AsyncSession
):
    resp = await _register(client)
    assert resp.status_code == 201
    assert resp.json()["username"] == "alice"
    assert resp.json()["global_role"] == "player"

    cookie = _session_cookie(resp)
    assert "httponly" in cookie.lower()
    me = await client.get("/api/v1/auth/me", headers={"Cookie": cookie.split(";")[0]})
    assert me.json()["username"] == "alice"

    user = (await db_session.execute(select(User))).scalar_one()
    assert user.email == "alice@example.com"  # normalised
    assert user.discord_id is None
    assert user.password_hash and "correct-horse" not in user.password_hash


@pytest.mark.asyncio
async def test_login_by_username_or_email_opens_session(
    client: AsyncClient, db_session: AsyncSession
):
    await _register(client)
    for identifier in ("alice", "ALICE", "alice@example.com"):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"identifier": identifier, "password": "correct-horse"},
            headers=ORIGIN,
        )
        assert resp.status_code == 200, identifier
        assert _session_cookie(resp)
    # one session from register + one per login
    assert len((await db_session.execute(select(UserSession))).all()) == 4


@pytest.mark.asyncio
async def test_admin_username_gets_admin_role(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "admin_usernames", " Alice , bob")
    resp = await _register(client)
    assert resp.json()["global_role"] == "admin"


@pytest.mark.asyncio
async def test_logout_ends_password_session(client: AsyncClient):
    cookie = _session_cookie(await _register(client)).split(";")[0]
    headers = {"Cookie": cookie, **ORIGIN}
    assert (
        await client.post("/api/v1/auth/logout", headers=headers)
    ).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
