"""WebSocket transport tests for the team exchange space (B-16, B-17).

These use Starlette's synchronous ``TestClient`` (the async httpx client cannot
open WebSockets). The app is bound to a throwaway file-backed SQLite database so
the lifespan, the HTTP requests and the socket task all share one schema.
"""

import asyncio
import os
import shutil
import tempfile
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app
from app.models.entities import Team, TeamMember, Tournament, User
from app.realtime.manager import manager
from app.services.auth_service import create_session
from tests.helpers import TRUSTED_ORIGIN


def _headers(token: str) -> dict[str, str]:
    """Headers a browser sends: session cookie plus its own Origin."""
    return {
        "Cookie": f"{settings.session_cookie_name}={token}",
        "Origin": TRUSTED_ORIGIN,
    }


@pytest.fixture
def ws_client(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "ws.db").replace("\\", "/")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False
    )
    ids: dict[str, uuid.UUID] = {}
    tokens: dict[str, str] = {}

    async def _prepare() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            seed_admin = User(
                id=uuid.uuid4(),
                username="ws_admin",
                discord_id=uuid.uuid4().hex,
                global_role="admin",
            )
            captain = User(
                id=uuid.uuid4(),
                username="ws_captain",
                discord_id=uuid.uuid4().hex,
                global_role="player",
            )
            member = User(
                id=uuid.uuid4(),
                username="ws_member",
                discord_id=uuid.uuid4().hex,
                global_role="player",
            )
            outsider = User(
                id=uuid.uuid4(),
                username="ws_outsider",
                discord_id=uuid.uuid4().hex,
                global_role="player",
            )
            session.add_all([seed_admin, captain, member, outsider])
            await session.flush()
            tournament = Tournament(
                id=uuid.uuid4(),
                name="WS Cup",
                game="Valorant",
                status="registration_open",
                created_by=seed_admin.id,
            )
            session.add(tournament)
            await session.flush()
            team = Team(
                id=uuid.uuid4(),
                tournament_id=tournament.id,
                name="WS Team",
                captain_id=captain.id,
            )
            session.add(team)
            await session.flush()
            session.add_all(
                [
                    TeamMember(
                        team_id=team.id,
                        user_id=captain.id,
                        tournament_id=tournament.id,
                        game_role="captain",
                    ),
                    TeamMember(
                        team_id=team.id,
                        user_id=member.id,
                        tournament_id=tournament.id,
                        game_role="duelist",
                    ),
                ]
            )
            await session.commit()
            ids.update(
                team=team.id, captain=captain.id, member=member.id, outsider=outsider.id
            )
            tokens.update(
                {
                    name: await create_session(session, user)
                    for name, user in (
                        ("captain", captain),
                        ("member", member),
                        ("outsider", outsider),
                    )
                }
            )
            await session.commit()

    asyncio.run(_prepare())

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    manager._rooms.clear()

    with TestClient(app) as test_client:
        test_client.ids = ids
        test_client.tokens = tokens
        yield test_client

    app.dependency_overrides.clear()
    manager._rooms.clear()
    asyncio.run(engine.dispose())
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_ws_member_receives_broadcast(ws_client):
    team_id = ws_client.ids["team"]
    member = _headers(ws_client.tokens["member"])
    captain = _headers(ws_client.tokens["captain"])

    with ws_client.websocket_connect(
        f"/api/v1/teams/{team_id}/ws", headers=member
    ) as ws:
        assert ws.receive_json()["event"] == "connected"
        resp = ws_client.post(
            f"/api/v1/teams/{team_id}/messages",
            headers=captain,
            json={"content": "salut"},
        )
        assert resp.status_code == 201
        pushed = ws.receive_json()
        assert pushed["type"] == "message"
        assert pushed["data"]["content"] == "salut"
        assert pushed["data"]["author_username"] == "ws_captain"


def test_ws_bidirectional_send_persists(ws_client):
    team_id = ws_client.ids["team"]
    member = _headers(ws_client.tokens["member"])

    with ws_client.websocket_connect(
        f"/api/v1/teams/{team_id}/ws", headers=member
    ) as ws:
        ws.receive_json()  # connected
        ws.send_json({"type": "message", "content": "depuis-le-socket"})
        echoed = ws.receive_json()
        assert echoed["type"] == "message"
        assert echoed["data"]["content"] == "depuis-le-socket"

    history = ws_client.get(
        f"/api/v1/teams/{team_id}/messages",
        headers=member,
    )
    assert any(m["content"] == "depuis-le-socket" for m in history.json())


def test_ws_denied_when_no_session_cookie(ws_client):
    team_id = ws_client.ids["team"]
    with ws_client.websocket_connect(
        f"/api/v1/teams/{team_id}/ws", headers={"Origin": TRUSTED_ORIGIN}
    ) as ws:
        assert ws.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ws_denied_when_session_cookie_forged(ws_client):
    team_id = ws_client.ids["team"]
    with ws_client.websocket_connect(
        f"/api/v1/teams/{team_id}/ws", headers=_headers("forged-token")
    ) as ws:
        assert ws.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_ws_denied_when_origin_not_allowed(ws_client, origin):
    """A valid member cookie is useless from a foreign page (cross-site hijacking)."""
    team_id = ws_client.ids["team"]
    headers = {"Cookie": _headers(ws_client.tokens["member"])["Cookie"]}
    if origin:
        headers["Origin"] = origin
    with (
        pytest.raises(WebSocketDisconnect),
        ws_client.websocket_connect(f"/api/v1/teams/{team_id}/ws", headers=headers),
    ):
        pass


def test_ws_denied_when_only_query_token_given(ws_client):
    """The old ?token= credential is no longer accepted."""
    team_id = ws_client.ids["team"]
    token = ws_client.tokens["member"]
    with ws_client.websocket_connect(
        f"/api/v1/teams/{team_id}/ws?token={token}",
        headers={"Origin": TRUSTED_ORIGIN},
    ) as ws:
        assert ws.receive_json()["type"] == "error"


def test_ws_denied_when_not_member(ws_client):
    team_id = ws_client.ids["team"]
    outsider = _headers(ws_client.tokens["outsider"])
    with ws_client.websocket_connect(
        f"/api/v1/teams/{team_id}/ws", headers=outsider
    ) as ws:
        assert ws.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_ws_excluded_member_socket_revoked(ws_client):
    team_id = ws_client.ids["team"]
    member_id = ws_client.ids["member"]
    member = _headers(ws_client.tokens["member"])
    captain = _headers(ws_client.tokens["captain"])

    with ws_client.websocket_connect(
        f"/api/v1/teams/{team_id}/ws", headers=member
    ) as ws:
        assert ws.receive_json()["event"] == "connected"
        resp = ws_client.request(
            "DELETE",
            f"/api/v1/teams/{team_id}/members/{member_id}",
            headers=captain,
        )
        assert resp.status_code == 200
        revoked = ws.receive_json()
        assert revoked["type"] == "system"
        assert revoked["event"] == "revoked"
        assert revoked["reason"] == "excluded"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
