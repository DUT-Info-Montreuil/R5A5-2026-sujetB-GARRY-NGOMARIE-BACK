"""Functional tests for the team exchange space REST surface (B-16, B-18).

The WebSocket transport is covered separately in ``tests/test_chat_ws.py``.
"""

import uuid

import pytest
import pytest_asyncio

from app.core.security import create_access_token, get_password_hash
from app.models.entities import Team, TeamMember, User


def auth_header(user: User) -> dict[str, str]:
    token = create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.global_role}
    )
    return {"Authorization": f"Bearer {token}"}


async def _make_user(db, name: str, role: str = "player") -> User:
    user = User(
        id=uuid.uuid4(),
        username=name,
        email=f"{name}@chat.test",
        hashed_password=get_password_hash("SecretPass123!"),
        global_role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def chat_env(db_session, open_tournament):
    captain = await _make_user(db_session, "fx_captain")
    member = await _make_user(db_session, "fx_member")
    admin = await _make_user(db_session, "fx_admin", role="admin")
    team = Team(
        id=uuid.uuid4(),
        tournament_id=open_tournament.id,
        name="Fixture Team",
        captain_id=captain.id,
    )
    db_session.add(team)
    await db_session.flush()
    db_session.add_all(
        [
            TeamMember(
                team_id=team.id,
                user_id=captain.id,
                tournament_id=open_tournament.id,
                game_role="captain",
            ),
            TeamMember(
                team_id=team.id,
                user_id=member.id,
                tournament_id=open_tournament.id,
                game_role="duelist",
            ),
        ]
    )
    await db_session.commit()
    await db_session.refresh(team)
    return {"team": team, "captain": captain, "member": member, "admin": admin}


def _url(team_id: uuid.UUID) -> str:
    return f"/api/v1/teams/{team_id}/messages"


@pytest.mark.asyncio
async def test_member_posts_then_reads_history(client, chat_env):
    team, member, captain = chat_env["team"], chat_env["member"], chat_env["captain"]

    resp = await client.post(
        _url(team.id), headers=auth_header(member), json={"content": "  bonjour  "}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["content"] == "bonjour"  # trimmed
    assert body["author_username"] == member.username

    history = await client.get(_url(team.id), headers=auth_header(captain))
    assert history.status_code == 200
    assert [m["content"] for m in history.json()] == ["bonjour"]


@pytest.mark.asyncio
async def test_post_rejected_when_blank(client, chat_env):
    resp = await client.post(
        _url(chat_env["team"].id),
        headers=auth_header(chat_env["member"]),
        json={"content": "   "},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_rejected_when_too_long(client, chat_env):
    resp = await client.post(
        _url(chat_env["team"].id),
        headers=auth_header(chat_env["member"]),
        json={"content": "x" * 5000},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_can_read_active_team_chat(client, chat_env):
    resp = await client.get(
        _url(chat_env["team"].id), headers=auth_header(chat_env["admin"])
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_messages_unknown_team_is_404(client, chat_env):
    resp = await client.get(
        _url(uuid.uuid4()), headers=auth_header(chat_env["member"])
    )
    assert resp.status_code == 404
