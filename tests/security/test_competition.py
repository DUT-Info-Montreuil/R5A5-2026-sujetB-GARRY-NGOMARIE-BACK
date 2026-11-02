"""Security tests -- tournament lifecycle and competition (B-03, B-04, B-11..B-15).

Covers the rules of ``context.md`` section 8 for state transitions, result entry
and forfeits: an unauthorized caller, a wrong tournament state or an unknown
team must be refused. One negative test per rule, named
``test_<action>_denied_when_<condition>``.
"""

import uuid

import pytest
import pytest_asyncio

from app.models.entities import Tournament
from tests.helpers import create_team, session_headers

NO_TEAM = "00000000-0000-0000-0000-000000000000"


@pytest_asyncio.fixture
async def two_teams(db_session, open_tournament):
    a, users_a = await create_team(db_session, open_tournament, "Alpha")
    b, _ = await create_team(db_session, open_tournament, "Bravo")
    return a, b, users_a


@pytest_asyncio.fixture
async def captain_headers(db_session, two_teams):
    _, _, users_a = two_teams
    return await session_headers(db_session, users_a[0].id)


async def _post(client, path, headers=None, json=None):
    return await client.post(f"/api/v1/tournaments/{path}", headers=headers, json=json)


async def _matches(client, tournament):
    return (await client.get(f"/api/v1/tournaments/{tournament.id}/matches")).json()


async def _running(client, admin_headers, tournament):
    await _post(client, f"{tournament.id}/close-registration", admin_headers)
    await _post(client, f"{tournament.id}/start", admin_headers)
    return (await _matches(client, tournament))[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["close-registration", "start"])
async def test_change_state_denied_when_caller_is_not_admin(
    client,
    db_session,
    player_headers,
    captain_headers,
    open_tournament,
    two_teams,
    action,
):
    for headers in (player_headers, captain_headers):
        response = await _post(client, f"{open_tournament.id}/{action}", headers)
        assert response.status_code == 403
    await db_session.refresh(open_tournament)
    assert open_tournament.status == "registration_open"


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["close-registration", "start"])
async def test_change_state_denied_when_unauthenticated(
    client, open_tournament, action
):
    response = await _post(client, f"{open_tournament.id}/{action}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_close_registration_denied_when_fewer_than_two_teams(
    client, admin_headers, db_session, open_tournament
):
    await create_team(db_session, open_tournament, "Solo")
    response = await _post(
        client, f"{open_tournament.id}/close-registration", admin_headers
    )
    assert response.status_code == 400
    await db_session.refresh(open_tournament)
    assert open_tournament.status == "registration_open"


@pytest.mark.asyncio
async def test_close_registration_denied_when_already_closed(
    client, admin_headers, open_tournament, two_teams
):
    await _post(client, f"{open_tournament.id}/close-registration", admin_headers)
    response = await _post(
        client, f"{open_tournament.id}/close-registration", admin_headers
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_start_denied_when_registration_still_open(
    client, admin_headers, open_tournament, two_teams
):
    response = await _post(client, f"{open_tournament.id}/start", admin_headers)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_start_denied_when_already_running(
    client, admin_headers, open_tournament, two_teams
):
    await _running(client, admin_headers, open_tournament)
    response = await _post(client, f"{open_tournament.id}/start", admin_headers)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_enter_result_denied_when_caller_is_not_admin(
    client, admin_headers, player_headers, captain_headers, open_tournament, two_teams
):
    match = await _running(client, admin_headers, open_tournament)
    for headers, expected in (
        (player_headers, 403),
        (captain_headers, 403),
        (None, 401),
    ):
        response = await _post(
            client,
            f"{open_tournament.id}/matches/{match['id']}/result",
            headers,
            {"team1_score": 3, "team2_score": 0},
        )
        assert response.status_code == expected
    assert (await _matches(client, open_tournament))[0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_declare_forfeit_denied_when_caller_is_not_admin(
    client, admin_headers, player_headers, captain_headers, open_tournament, two_teams
):
    a, _, _ = two_teams
    match = await _running(client, admin_headers, open_tournament)
    for headers, expected in (
        (player_headers, 403),
        (captain_headers, 403),
        (None, 401),
    ):
        response = await _post(
            client,
            f"{open_tournament.id}/matches/{match['id']}/forfeit",
            headers,
            {"forfeiting_team_id": str(a.id)},
        )
        assert response.status_code == expected
    assert (await _matches(client, open_tournament))[0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_enter_result_denied_when_tournament_not_running(
    client, admin_headers, open_tournament, two_teams
):
    await _post(client, f"{open_tournament.id}/close-registration", admin_headers)
    match = (await _matches(client, open_tournament))[0]
    response = await _post(
        client,
        f"{open_tournament.id}/matches/{match['id']}/result",
        admin_headers,
        {"team1_score": 1, "team2_score": 0},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_enter_result_denied_when_a_team_is_unknown(
    client, admin_headers, db_session, open_tournament
):
    for name in "ABCD":
        await create_team(db_session, open_tournament, name)
    await _post(client, f"{open_tournament.id}/close-registration", admin_headers)
    await _post(client, f"{open_tournament.id}/start", admin_headers)
    final = next(m for m in await _matches(client, open_tournament) if m["round"] == 2)
    response = await _post(
        client,
        f"{open_tournament.id}/matches/{final['id']}/result",
        admin_headers,
        {"team1_score": 1, "team2_score": 0},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_enter_result_denied_when_match_already_validated(
    client, admin_headers, open_tournament, two_teams
):
    match = await _running(client, admin_headers, open_tournament)
    path = f"{open_tournament.id}/matches/{match['id']}/result"
    first = await _post(
        client, path, admin_headers, {"team1_score": 2, "team2_score": 0}
    )
    assert first.status_code == 200
    again = await _post(
        client, path, admin_headers, {"team1_score": 0, "team2_score": 9}
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_enter_result_denied_when_match_belongs_to_another_tournament(
    client, admin_headers, admin_user, db_session, open_tournament, two_teams
):
    match = await _running(client, admin_headers, open_tournament)
    other = Tournament(
        id=uuid.uuid4(),
        name="Other",
        game="CS2",
        status="running",
        created_by=admin_user.id,
    )
    db_session.add(other)
    await db_session.commit()
    response = await _post(
        client,
        f"{other.id}/matches/{match['id']}/result",
        admin_headers,
        {"team1_score": 1, "team2_score": 0},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_declare_forfeit_denied_when_team_is_not_in_match(
    client, admin_headers, open_tournament, two_teams
):
    match = await _running(client, admin_headers, open_tournament)
    response = await _post(
        client,
        f"{open_tournament.id}/matches/{match['id']}/forfeit",
        admin_headers,
        {"forfeiting_team_id": NO_TEAM},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_read_chat_denied_when_team_eliminated_by_result(
    client, admin_headers, db_session, open_tournament, two_teams
):
    """B-18 producer: entering a result closes the loser's exchange space."""
    _, b, _ = two_teams
    match = await _running(client, admin_headers, open_tournament)
    await _post(
        client,
        f"{open_tournament.id}/matches/{match['id']}/result",
        admin_headers,
        {"team1_score": 5, "team2_score": 1},
    )
    loser_captain = await session_headers(db_session, b.captain_id)
    denied = await client.get(f"/api/v1/teams/{b.id}/messages", headers=loser_captain)
    assert denied.status_code == 403
    allowed = await client.get(f"/api/v1/teams/{b.id}/messages", headers=admin_headers)
    assert allowed.status_code == 200


def test_watch_tournament_denied_when_origin_not_allowed():
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from app.main import app

    url = f"/api/v1/tournaments/{NO_TEAM}/ws"
    with (
        TestClient(app) as tc,
        pytest.raises(WebSocketDisconnect),
        tc.websocket_connect(url, headers={"Origin": "http://evil.example"}),
    ):
        pass
