"""Security tests -- team exchange space (B-16, B-17, B-18).

Covers the chat rules of ``context.md`` section 8:

- read team chat: current member of that team, OR admin
- post to team chat: current member; team not eliminated
- excluded member: refused immediately after exclusion (B-17)
- eliminated team: members denied / space closed, admin read still allowed (B-18)

One negative test per rule, named ``test_<action>_denied_when_<condition>``.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.models.entities import Team, TeamMember, User
from tests.helpers import session_headers


async def _make_user(db, name: str, role: str = "player") -> User:
    user = User(
        id=uuid.uuid4(),
        username=name,
        discord_id=uuid.uuid4().hex,
        global_role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_team(db, tournament, captain, member, *, eliminated=False) -> Team:
    team = Team(
        id=uuid.uuid4(),
        tournament_id=tournament.id,
        name=f"Team-{uuid.uuid4().hex[:6]}",
        captain_id=captain.id,
        is_eliminated=eliminated,
    )
    db.add(team)
    await db.flush()
    db.add_all(
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
    await db.commit()
    await db.refresh(team)
    return team


@pytest_asyncio.fixture
async def chat_env(db_session, open_tournament):
    captain = await _make_user(db_session, "chat_captain")
    member = await _make_user(db_session, "chat_member")
    outsider = await _make_user(db_session, "chat_outsider")
    admin = await _make_user(db_session, "chat_admin", role="admin")
    team = await _make_team(db_session, open_tournament, captain, member)
    return {
        "db": db_session,
        "team": team,
        "captain": captain,
        "member": member,
        "outsider": outsider,
        "admin": admin,
        "headers": {
            "captain": await session_headers(db_session, captain.id),
            "member": await session_headers(db_session, member.id),
            "outsider": await session_headers(db_session, outsider.id),
            "admin": await session_headers(db_session, admin.id),
        },
    }


def _messages_url(team_id: uuid.UUID) -> str:
    return f"/api/v1/teams/{team_id}/messages"


@pytest.mark.asyncio
async def test_read_chat_denied_when_unauthenticated(client, chat_env):
    resp = await client.get(_messages_url(chat_env["team"].id))
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_read_chat_denied_when_not_member(client, chat_env):
    resp = await client.get(
        _messages_url(chat_env["team"].id), headers=chat_env["headers"]["outsider"]
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_chat_denied_when_unauthenticated(client, chat_env):
    resp = await client.post(_messages_url(chat_env["team"].id), json={"content": "hi"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_post_chat_denied_when_not_member(client, chat_env):
    resp = await client.post(
        _messages_url(chat_env["team"].id),
        headers=chat_env["headers"]["outsider"],
        json={"content": "hi"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_chat_denied_when_excluded_member(client, chat_env):
    """B-17: exclusion takes effect on the very next request, no cached authz."""
    db = chat_env["db"]
    await db.execute(
        delete(TeamMember).where(
            TeamMember.team_id == chat_env["team"].id,
            TeamMember.user_id == chat_env["member"].id,
        )
    )
    await db.commit()

    resp = await client.post(
        _messages_url(chat_env["team"].id),
        headers=chat_env["headers"]["member"],
        json={"content": "still here?"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_chat_denied_when_team_eliminated(client, chat_env):
    """B-18: an eliminated team's space is closed to its own members."""
    db = chat_env["db"]
    chat_env["team"].is_eliminated = True
    await db.commit()

    resp = await client.post(
        _messages_url(chat_env["team"].id),
        headers=chat_env["headers"]["member"],
        json={"content": "gg"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_read_chat_denied_when_team_eliminated_and_member(client, chat_env):
    """B-18: members lose read access once the team is eliminated."""
    db = chat_env["db"]
    chat_env["team"].is_eliminated = True
    await db.commit()

    resp = await client.get(
        _messages_url(chat_env["team"].id), headers=chat_env["headers"]["member"]
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_read_chat_allowed_when_admin_and_team_eliminated(client, chat_env):
    """B-18: the admin can still read a closed space."""
    db = chat_env["db"]
    chat_env["team"].is_eliminated = True
    await db.commit()

    resp = await client.get(
        _messages_url(chat_env["team"].id), headers=chat_env["headers"]["admin"]
    )
    assert resp.status_code == 200
