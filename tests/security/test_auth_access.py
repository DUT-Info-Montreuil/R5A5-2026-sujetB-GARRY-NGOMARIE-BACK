"""Negative security tests for authentication and the cookie session (X-01).

Naming: test_<action>_denied_when_<condition>.
"""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_session_token
from app.models.entities import User, UserSession, utc_now
from app.services import discord_oauth
from app.services.discord_oauth import DiscordAuthError, DiscordIdentity
from tests.helpers import TRUSTED_ORIGIN, session_headers

TOURNAMENT = {"name": "Cup", "game": "Valorant"}


@pytest.mark.asyncio
async def test_me_denied_when_no_session_cookie(client: AsyncClient):
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_me_denied_when_session_cookie_is_forged(client: AsyncClient):
    resp = await client.get(
        "/api/v1/auth/me", headers={"Cookie": "session=not-a-real-token"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_denied_when_session_expired(
    client: AsyncClient, db_session: AsyncSession, player_user: User, player_headers
):
    await db_session.execute(
        update(UserSession).values(expires_at=utc_now() - timedelta(seconds=1))
    )
    await db_session.commit()
    assert (
        await client.get("/api/v1/auth/me", headers=player_headers)
    ).status_code == 401


@pytest.mark.asyncio
async def test_me_denied_when_session_logged_out(client: AsyncClient, player_headers):
    assert (
        await client.get("/api/v1/auth/me", headers=player_headers)
    ).status_code == 200
    out = await client.post("/api/v1/auth/logout", headers=player_headers)
    assert out.status_code == 204
    # the very same cookie is now refused: revocation is server-side
    assert (
        await client.get("/api/v1/auth/me", headers=player_headers)
    ).status_code == 401


@pytest.mark.asyncio
async def test_logout_denied_when_unauthenticated(client: AsyncClient):
    resp = await client.post("/api/v1/auth/logout", headers={"Origin": TRUSTED_ORIGIN})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_tournament_denied_when_player_session(
    client: AsyncClient, player_headers
):
    resp = await client.post(
        "/api/v1/tournaments", json=TOURNAMENT, headers=player_headers
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_tournament_denied_when_authorization_header_only(
    client: AsyncClient,
):
    """A bearer token is no longer an accepted credential."""
    resp = await client.post(
        "/api/v1/tournaments",
        json=TOURNAMENT,
        headers={"Authorization": "Bearer anything", "Origin": TRUSTED_ORIGIN},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_action_denied_when_role_revoked_in_db(
    client: AsyncClient, db_session: AsyncSession, admin_user: User, admin_headers
):
    """Role is re-read from the DB on every request, not stored in the cookie."""
    ok = await client.post(
        "/api/v1/tournaments", json=TOURNAMENT, headers=admin_headers
    )
    assert ok.status_code == 201
    await db_session.execute(update(User).values(global_role="player"))
    await db_session.commit()
    denied = await client.post(
        "/api/v1/tournaments", json=TOURNAMENT, headers=admin_headers
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_state_change_denied_when_origin_missing(
    client: AsyncClient, admin_headers
):
    headers = {"Cookie": admin_headers["Cookie"]}
    resp = await client.post("/api/v1/tournaments", json=TOURNAMENT, headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_state_change_denied_when_origin_foreign(
    client: AsyncClient, admin_headers
):
    headers = {"Cookie": admin_headers["Cookie"], "Origin": "https://evil.example"}
    resp = await client.post("/api/v1/tournaments", json=TOURNAMENT, headers=headers)
    assert resp.status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/auth/token"),
        ("POST", "/api/v1/auth/dev-token/00000000-0000-0000-0000-000000000000"),
        ("GET", "/api/v1/auth/users"),
    ],
)
@pytest.mark.asyncio
async def test_legacy_auth_denied_when_endpoint_removed(
    client: AsyncClient, method: str, path: str
):
    resp = await client.request(method, path, json={})
    assert resp.status_code in (404, 405)


@pytest.mark.asyncio
async def test_discord_callback_denied_when_flow_cookie_missing(client: AsyncClient):
    resp = await client.get(
        "/api/v1/auth/discord/callback", params={"code": "abc", "state": "s"}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_discord_callback_denied_when_state_mismatch(
    client: AsyncClient, db_session: AsyncSession
):
    resp = await client.get(
        "/api/v1/auth/discord/callback",
        params={"code": "abc", "state": "attacker-state"},
        headers={"Cookie": "oauth_flow=real-state.verifier"},
    )
    assert resp.status_code == 400
    assert (await db_session.execute(select(UserSession))).first() is None


@pytest.mark.asyncio
async def test_discord_callback_denied_when_discord_rejects_identity(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    async def refuse(code, verifier):
        raise DiscordAuthError("nope")

    monkeypatch.setattr(discord_oauth, "fetch_identity", refuse)
    resp = await client.get(
        "/api/v1/auth/discord/callback",
        params={"code": "abc", "state": "s"},
        headers={"Cookie": "oauth_flow=s.verifier"},
    )
    assert resp.status_code == 401
    assert (await db_session.execute(select(User))).first() is None
    assert (await db_session.execute(select(UserSession))).first() is None


@pytest.mark.asyncio
async def test_discord_login_denied_when_not_configured(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "discord_client_id", "")
    assert (await client.get("/api/v1/auth/discord/login")).status_code == 503


@pytest.mark.asyncio
async def test_admin_role_denied_when_id_not_in_allowlist(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """The role comes from ADMIN_DISCORD_IDS only; nothing in the request can set it."""
    monkeypatch.setattr(settings, "admin_discord_ids", "777")

    async def fake_fetch(code, verifier):
        return DiscordIdentity(id="666", username="mallory")

    monkeypatch.setattr(discord_oauth, "fetch_identity", fake_fetch)
    await client.get(
        "/api/v1/auth/discord/callback",
        params={"code": "abc", "state": "s", "global_role": "admin"},
        headers={"Cookie": "oauth_flow=s.verifier"},
    )
    user = (await db_session.execute(select(User))).scalar_one()
    assert user.global_role == "player"


@pytest.mark.asyncio
async def test_admin_role_revoked_when_id_removed_from_allowlist(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    async def fake_fetch(code, verifier):
        return DiscordIdentity(id="777", username="boss")

    monkeypatch.setattr(discord_oauth, "fetch_identity", fake_fetch)
    call = {
        "params": {"code": "abc", "state": "s"},
        "headers": {"Cookie": "oauth_flow=s.verifier"},
    }
    monkeypatch.setattr(settings, "admin_discord_ids", "777")
    await client.get("/api/v1/auth/discord/callback", **call)
    assert (await db_session.execute(select(User))).scalar_one().global_role == "admin"

    monkeypatch.setattr(settings, "admin_discord_ids", "")
    await client.get("/api/v1/auth/discord/callback", **call)
    await db_session.commit()
    db_session.expire_all()
    assert (await db_session.execute(select(User))).scalar_one().global_role == "player"


@pytest.mark.asyncio
async def test_session_token_stored_hashed_never_raw(
    db_session: AsyncSession, player_user: User
):
    headers = await session_headers(db_session, player_user.id)
    raw = headers["Cookie"].split("=", 1)[1]
    row = (await db_session.execute(select(UserSession))).scalar_one()
    assert row.token_hash == hash_session_token(raw)
    assert raw not in row.token_hash


def _stub_discord(monkeypatch, *, token_status=200, me_status=200, profile=None):
    class Resp:
        def __init__(self, status, body):
            self.status_code = status
            self._body = body

        def json(self):
            return self._body

    class Http:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a): ...
        async def post(self, *a, **k):
            return Resp(token_status, {"access_token": "at"})

        async def get(self, *a, **k):
            return Resp(me_status, GOOD_PROFILE if profile is None else profile)

    monkeypatch.setattr(discord_oauth.httpx, "AsyncClient", Http)


GOOD_PROFILE = {"id": "123", "username": "alice"}


@pytest.mark.asyncio
async def test_discord_identity_accepted_when_profile_valid(monkeypatch):
    _stub_discord(monkeypatch)
    identity = await discord_oauth.fetch_identity("c", "v")
    assert identity == DiscordIdentity(id="123", username="alice")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"token_status": 400},
        {"me_status": 401},
        {"profile": {"username": "no-id"}},
        {"profile": {"id": "1"}},
    ],
)
@pytest.mark.asyncio
async def test_discord_identity_denied_when_exchange_or_profile_bad(
    monkeypatch, kwargs
):
    _stub_discord(monkeypatch, **kwargs)
    with pytest.raises(DiscordAuthError):
        await discord_oauth.fetch_identity("c", "v")
