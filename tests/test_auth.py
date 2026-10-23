"""Functional tests of the Discord login flow (Discord itself is stubbed)."""

from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import User, UserSession
from app.services import discord_oauth
from app.services.discord_oauth import DiscordIdentity
from tests.helpers import TRUSTED_ORIGIN

FLOW = "state-1.verifier-1"


@pytest.fixture
def discord_identity(monkeypatch):
    """Make Discord 'return' the identity stored in the returned dict."""
    box = {"identity": DiscordIdentity(id="111", username="alice")}

    async def fake_fetch(code: str, verifier: str) -> DiscordIdentity:
        assert verifier == "verifier-1"
        return box["identity"]

    monkeypatch.setattr(discord_oauth, "fetch_identity", fake_fetch)
    return box


async def _callback(client: AsyncClient):
    return await client.get(
        "/api/v1/auth/discord/callback",
        params={"code": "abc", "state": "state-1"},
        headers={"Cookie": f"oauth_flow={FLOW}"},
    )


@pytest.mark.asyncio
async def test_discord_login_redirects_with_state_and_pkce(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "discord_client_id", "client-id")
    resp = await client.get("/api/v1/auth/discord/login")
    assert resp.status_code == 302
    url = urlparse(resp.headers["location"])
    query = parse_qs(url.query)
    assert url.netloc == "discord.com"
    assert query["scope"] == ["identify"]
    assert query["client_id"] == ["client-id"]
    assert query["code_challenge_method"] == ["S256"]
    flow = resp.cookies["oauth_flow"]
    state, _verifier = flow.split(".")
    assert query["state"] == [state]
    assert "httponly" in resp.headers["set-cookie"].lower()


@pytest.mark.asyncio
async def test_discord_callback_creates_player_and_session(
    client: AsyncClient, db_session: AsyncSession, discord_identity
):
    resp = await _callback(client)
    assert resp.status_code == 302
    assert resp.headers["location"] == settings.frontend_url

    set_cookies = resp.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookies if c.startswith("session="))
    assert "httponly" in session_cookie.lower()
    assert "samesite=lax" in session_cookie.lower()

    user = (await db_session.execute(select(User))).scalar_one()
    assert user.discord_id == "111"
    assert user.global_role == "player"
    assert user.username == "alice"
    sessions = (await db_session.execute(select(UserSession))).scalars().all()
    assert len(sessions) == 1
    # only a hash is stored, never the cookie value
    token = session_cookie.split(";")[0].split("=", 1)[1]
    assert sessions[0].token_hash != token


@pytest.mark.asyncio
async def test_me_returns_user_for_valid_session(client: AsyncClient, discord_identity):
    resp = await _callback(client)
    token = next(
        c for c in resp.headers.get_list("set-cookie") if c.startswith("session=")
    ).split(";")[0]
    me = await client.get("/api/v1/auth/me", headers={"Cookie": token})
    assert me.status_code == 200
    assert me.json()["username"] == "alice"
    assert me.json()["global_role"] == "player"


@pytest.mark.asyncio
async def test_second_login_reuses_the_same_user(
    client: AsyncClient, db_session: AsyncSession, discord_identity
):
    await _callback(client)
    await _callback(client)
    assert len((await db_session.execute(select(User))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_username_collision_gets_a_suffix(
    client: AsyncClient, db_session: AsyncSession, discord_identity
):
    await _callback(client)
    discord_identity["identity"] = DiscordIdentity(id="222", username="alice")
    await _callback(client)
    names = {u.username for u in (await db_session.execute(select(User))).scalars()}
    assert len(names) == 2
    assert "alice" in names


@pytest.mark.asyncio
async def test_admin_discord_id_gets_admin_role(
    client: AsyncClient, db_session: AsyncSession, discord_identity, monkeypatch
):
    monkeypatch.setattr(settings, "admin_discord_ids", " 111 , 999")
    await _callback(client)
    user = (await db_session.execute(select(User))).scalar_one()
    assert user.global_role == "admin"


@pytest.mark.asyncio
async def test_logout_deletes_session_and_clears_cookie(
    client: AsyncClient, db_session: AsyncSession, discord_identity
):
    resp = await _callback(client)
    token = next(
        c for c in resp.headers.get_list("set-cookie") if c.startswith("session=")
    ).split(";")[0]
    out = await client.post(
        "/api/v1/auth/logout", headers={"Cookie": token, "Origin": TRUSTED_ORIGIN}
    )
    assert out.status_code == 204
    assert "session=" in out.headers["set-cookie"]
    assert (await db_session.execute(select(UserSession))).first() is None
