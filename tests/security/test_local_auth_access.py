"""Negative security tests for password accounts (X-01).

Naming: test_<action>_denied_when_<condition>.
"""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import login_throttle
from app.models.entities import User, UserSession, utc_now
from tests.helpers import TRUSTED_ORIGIN, create_user

ORIGIN = {"Origin": TRUSTED_ORIGIN}
ALICE = {"username": "alice", "email": "alice@example.com", "password": "correct-horse"}


async def _register(client: AsyncClient, body: dict = ALICE):
    return await client.post("/api/v1/auth/register", json=body, headers=ORIGIN)


async def _login(client: AsyncClient, identifier: str, password: str):
    return await client.post(
        "/api/v1/auth/login",
        json={"identifier": identifier, "password": password},
        headers=ORIGIN,
    )


@pytest.mark.asyncio
async def test_register_denied_when_role_supplied_by_client(
    client: AsyncClient, db_session: AsyncSession
):
    """A global_role in the body is ignored: the role only comes from the env."""
    resp = await _register(client, {**ALICE, "global_role": "admin"})
    assert resp.status_code == 201
    assert resp.json()["global_role"] == "player"
    user = (await db_session.execute(select(User))).scalar_one()
    assert user.global_role == "player"


@pytest.mark.parametrize(
    "field", [{"username": "ALICE"}, {"email": "ALICE@example.com"}]
)
@pytest.mark.asyncio
async def test_register_denied_when_username_or_email_taken(
    client: AsyncClient, field: dict
):
    await _register(client)
    other = {"username": "bob", "email": "bob@example.com", "password": "pw-12345678"}
    assert (await _register(client, {**other, **field})).status_code == 409


@pytest.mark.asyncio
async def test_register_denied_when_name_taken_by_discord_account(
    client: AsyncClient, db_session: AsyncSession
):
    await create_user(db_session, "alice")
    assert (await _register(client)).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {**ALICE, "password": "short"},
        {**ALICE, "email": "not-an-email"},
        {**ALICE, "username": "a"},
        {**ALICE, "username": "bad name!"},
    ],
)
@pytest.mark.asyncio
async def test_register_denied_when_payload_invalid(client: AsyncClient, body: dict):
    assert (await _register(client, body)).status_code == 422


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
@pytest.mark.asyncio
async def test_register_denied_when_origin_not_allowed(
    client: AsyncClient, db_session: AsyncSession, origin
):
    headers = {"Origin": origin} if origin else {}
    resp = await client.post("/api/v1/auth/register", json=ALICE, headers=headers)
    assert resp.status_code == 403
    assert (await db_session.execute(select(User))).first() is None


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
@pytest.mark.asyncio
async def test_login_denied_when_origin_not_allowed(client: AsyncClient, origin):
    """Login CSRF: a foreign page must not log a visitor into another account."""
    await _register(client)
    headers = {"Origin": origin} if origin else {}
    resp = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "alice", "password": "correct-horse"},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "set-cookie" not in resp.headers


@pytest.mark.asyncio
async def test_login_denied_when_password_wrong(client: AsyncClient):
    await _register(client)
    resp = await _login(client, "alice", "wrong-password")
    assert resp.status_code == 401
    assert "set-cookie" not in resp.headers


@pytest.mark.asyncio
async def test_login_denied_when_user_unknown_with_same_message(client: AsyncClient):
    await _register(client)
    unknown = await _login(client, "nobody", "correct-horse")
    wrong = await _login(client, "alice", "nope-nope")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


@pytest.mark.asyncio
async def test_login_denied_when_account_is_discord_only(
    client: AsyncClient, db_session: AsyncSession
):
    """A Discord account has no password: no password can ever open it."""
    await create_user(db_session, "discorduser")
    for pw in ("x", "correct-horse", "timing-equalizer"):
        assert (await _login(client, "discorduser", pw)).status_code == 401


@pytest.mark.asyncio
async def test_login_denied_when_too_many_failures(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 3)
    await _register(client)
    for _ in range(3):
        assert (await _login(client, "alice", "bad-guess")).status_code == 401
    # even the right password is refused while blocked
    blocked = await _login(client, "alice", "correct-horse")
    assert blocked.status_code == 429
    assert "set-cookie" not in blocked.headers


@pytest.mark.asyncio
async def test_login_throttle_not_shared_across_ips(client: AsyncClient, monkeypatch):
    """Failures from one client do not lock the owner out from another one."""
    monkeypatch.setattr(settings, "login_max_failures", 2)
    await _register(client)
    for _ in range(2):
        await _login(client, "alice", "bad-guess")
    assert (await _login(client, "alice", "correct-horse")).status_code == 429
    assert not login_throttle.is_blocked("203.0.113.9|alice")


@pytest.mark.asyncio
async def test_admin_action_denied_when_username_removed_from_allowlist(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "admin_usernames", "alice")
    assert (await _register(client)).json()["global_role"] == "admin"

    monkeypatch.setattr(settings, "admin_usernames", "")
    resp = await _login(client, "alice", "correct-horse")
    assert resp.json()["global_role"] == "player"
    cookie = resp.headers["set-cookie"].split(";")[0]
    create = await client.post(
        "/api/v1/tournaments",
        json={"name": "Cup", "game": "CS2"},
        headers={"Cookie": cookie, **ORIGIN},
    )
    assert create.status_code == 403


@pytest.mark.asyncio
async def test_password_session_denied_when_expired(
    client: AsyncClient, db_session: AsyncSession
):
    cookie = (await _register(client)).headers["set-cookie"].split(";")[0]
    await db_session.execute(
        update(UserSession).values(expires_at=utc_now() - timedelta(seconds=1))
    )
    await db_session.commit()
    me = await client.get("/api/v1/auth/me", headers={"Cookie": cookie})
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_password_never_returned_or_stored_in_clear(
    client: AsyncClient, db_session: AsyncSession
):
    resp = await _register(client)
    assert "correct-horse" not in resp.text
    assert "password" not in resp.json()
    user = (await db_session.execute(select(User))).scalar_one()
    assert user.password_hash.startswith("$argon2")


@pytest.mark.asyncio
async def test_discord_signup_denied_name_differing_only_by_case(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """A Discord 'Alice' must not reuse a local 'alice': login by name stays unique."""
    from app.services import discord_oauth
    from app.services.discord_oauth import DiscordIdentity

    await _register(client)

    async def fake_fetch(code, verifier):
        return DiscordIdentity(id="555", username="Alice")

    monkeypatch.setattr(discord_oauth, "fetch_identity", fake_fetch)
    await client.get(
        "/api/v1/auth/discord/callback",
        params={"code": "abc", "state": "s"},
        headers={"Cookie": "oauth_flow=s.verifier"},
    )
    names = [u.username for u in (await db_session.execute(select(User))).scalars()]
    assert len(names) == 2
    assert names.count("alice") == 1 and "Alice" not in names
    assert (await _login(client, "alice", "correct-horse")).status_code == 200
