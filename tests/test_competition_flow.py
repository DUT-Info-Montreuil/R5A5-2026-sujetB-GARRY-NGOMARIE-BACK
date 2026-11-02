"""Tournament lifecycle and bracket (B-03, B-04, B-12, B-13, B-14, B-15)."""

import pytest

from tests.helpers import create_team


async def _teams(db, tournament, count):
    return [
        (await create_team(db, tournament, f"T{i}"))[0] for i in range(1, count + 1)
    ]


async def _matches(client, tournament):
    return (await client.get(f"/api/v1/tournaments/{tournament.id}/matches")).json()


async def _close(client, headers, tournament):
    return await client.post(
        f"/api/v1/tournaments/{tournament.id}/close-registration", headers=headers
    )


async def _start(client, headers, tournament):
    return await client.post(
        f"/api/v1/tournaments/{tournament.id}/start", headers=headers
    )


async def _result(client, headers, tournament, match, s1, s2):
    return await client.post(
        f"/api/v1/tournaments/{tournament.id}/matches/{match['id']}/result",
        json={"team1_score": s1, "team2_score": s2},
        headers=headers,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("count", "rounds", "byes"),
    [(2, 1, 0), (3, 2, 1), (4, 2, 0), (5, 3, 3), (8, 3, 0)],
)
async def test_close_builds_bracket_sized_to_power_of_two(
    client, admin_headers, db_session, open_tournament, count, rounds, byes
):
    await _teams(db_session, open_tournament, count)
    response = await _close(client, admin_headers, open_tournament)
    assert response.status_code == 200
    assert response.json()["status"] == "registration_closed"

    matches = await _matches(client, open_tournament)
    assert max(m["round"] for m in matches) == rounds
    bye_matches = [m for m in matches if m["round"] == 1 and m["team2_id"] is None]
    assert len(bye_matches) == byes
    for m in bye_matches:
        assert m["status"] == "completed"
        assert m["winner_id"] == m["team1_id"]
    if byes:
        second = [m for m in matches if m["round"] == 2]
        placed = {m["team1_id"] for m in second} | {m["team2_id"] for m in second}
        assert {m["winner_id"] for m in bye_matches} <= placed


@pytest.mark.asyncio
async def test_byes_go_to_first_registered_teams(
    client, admin_headers, db_session, open_tournament
):
    teams = await _teams(db_session, open_tournament, 3)
    await _close(client, admin_headers, open_tournament)
    bye = next(
        m for m in await _matches(client, open_tournament) if m["team2_id"] is None
    )
    assert bye["team1_id"] == str(teams[0].id)


@pytest.mark.asyncio
async def test_full_tournament_advances_winners_and_finishes(
    client, admin_headers, db_session, open_tournament
):
    await _teams(db_session, open_tournament, 4)
    await _close(client, admin_headers, open_tournament)
    started = await _start(client, admin_headers, open_tournament)
    assert started.json()["status"] == "running"

    matches = await _matches(client, open_tournament)
    round1 = [m for m in matches if m["round"] == 1]
    final = next(m for m in matches if m["round"] == 2)
    assert final["status"] == "pending"
    assert all(m["status"] == "in_progress" for m in round1)

    response = await _result(client, admin_headers, open_tournament, round1[0], 3, 1)
    assert response.status_code == 200
    assert response.json()["winner_id"] == round1[0]["team1_id"]
    final = next(m for m in await _matches(client, open_tournament) if m["round"] == 2)
    assert final["status"] == "pending"  # one team known only: not playable yet

    await _result(client, admin_headers, open_tournament, round1[1], 0, 2)
    final = next(m for m in await _matches(client, open_tournament) if m["round"] == 2)
    assert final["status"] == "in_progress"
    assert final["team1_id"] == round1[0]["team1_id"]
    assert final["team2_id"] == round1[1]["team2_id"]

    await _result(client, admin_headers, open_tournament, final, 2, 1)
    await db_session.refresh(open_tournament)
    assert open_tournament.status == "finished"


@pytest.mark.asyncio
async def test_loser_is_eliminated_and_winner_is_not(
    client, admin_headers, db_session, open_tournament
):
    teams = await _teams(db_session, open_tournament, 2)
    await _close(client, admin_headers, open_tournament)
    await _start(client, admin_headers, open_tournament)
    (match,) = await _matches(client, open_tournament)
    await _result(client, admin_headers, open_tournament, match, 5, 2)
    await db_session.refresh(teams[0])
    await db_session.refresh(teams[1])
    assert not teams[0].is_eliminated
    assert teams[1].is_eliminated


@pytest.mark.asyncio
async def test_forfeit_qualifies_opponent(
    client, admin_headers, db_session, open_tournament
):
    teams = await _teams(db_session, open_tournament, 2)
    await _close(client, admin_headers, open_tournament)
    await _start(client, admin_headers, open_tournament)
    (match,) = await _matches(client, open_tournament)
    response = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/matches/{match['id']}/forfeit",
        json={"forfeiting_team_id": str(teams[0].id)},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "forfeit"
    assert response.json()["winner_id"] == str(teams[1].id)


@pytest.mark.asyncio
async def test_incomplete_team_forfeits_first_match_at_start(
    client, admin_headers, db_session, open_tournament
):
    (full,) = await _teams(db_session, open_tournament, 1)
    short, _ = await create_team(db_session, open_tournament, "Short", players=3)
    await _close(client, admin_headers, open_tournament)
    started = await _start(client, admin_headers, open_tournament)
    assert started.json()["status"] == "finished"
    (match,) = await _matches(client, open_tournament)
    assert match["status"] == "forfeit"
    assert match["winner_id"] == str(full.id)
    await db_session.refresh(short)
    assert short.is_eliminated


@pytest.mark.asyncio
async def test_both_incomplete_larger_roster_advances(
    client, admin_headers, db_session, open_tournament
):
    larger, _ = await create_team(db_session, open_tournament, "A", players=4)
    await create_team(db_session, open_tournament, "B", players=2)
    await _close(client, admin_headers, open_tournament)
    await _start(client, admin_headers, open_tournament)
    (match,) = await _matches(client, open_tournament)
    assert match["winner_id"] == str(larger.id)


@pytest.mark.asyncio
async def test_both_incomplete_equal_rosters_left_to_admin(
    client, admin_headers, db_session, open_tournament
):
    await create_team(db_session, open_tournament, "A", players=3)
    await create_team(db_session, open_tournament, "B", players=3)
    await _close(client, admin_headers, open_tournament)
    await _start(client, admin_headers, open_tournament)
    (match,) = await _matches(client, open_tournament)
    assert match["status"] == "in_progress"
    response = await _result(client, admin_headers, open_tournament, match, 1, 0)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_incomplete_team_with_bye_forfeits_when_it_first_plays(
    client, admin_headers, db_session, open_tournament
):
    await create_team(db_session, open_tournament, "Short", players=2)  # gets the bye
    await create_team(db_session, open_tournament, "B")
    await create_team(db_session, open_tournament, "C")
    await _close(client, admin_headers, open_tournament)
    await _start(client, admin_headers, open_tournament)
    real = next(
        m
        for m in await _matches(client, open_tournament)
        if m["round"] == 1 and m["team2_id"]
    )
    await _result(client, admin_headers, open_tournament, real, 1, 0)
    final = next(m for m in await _matches(client, open_tournament) if m["round"] == 2)
    assert final["status"] == "forfeit"
    assert final["winner_id"] == real["team1_id"]


@pytest.mark.asyncio
async def test_result_rejects_a_draw(
    client, admin_headers, db_session, open_tournament
):
    await _teams(db_session, open_tournament, 2)
    await _close(client, admin_headers, open_tournament)
    await _start(client, admin_headers, open_tournament)
    (match,) = await _matches(client, open_tournament)
    response = await _result(client, admin_headers, open_tournament, match, 2, 2)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_matches_of_unknown_tournament_is_404(client):
    response = await client.get(
        "/api/v1/tournaments/00000000-0000-0000-0000-000000000000/matches"
    )
    assert response.status_code == 404


@pytest.fixture
def spy(monkeypatch):
    from app.realtime.manager import manager

    calls = {"broadcast": [], "revoke": []}

    async def broadcast(room, payload, **_):
        calls["broadcast"].append((room, payload))

    async def revoke(room, user_id, *, reason):
        calls["revoke"].append((room, user_id, reason))

    monkeypatch.setattr(manager, "broadcast", broadcast)
    monkeypatch.setattr(manager, "revoke", revoke)
    return calls


@pytest.mark.asyncio
async def test_transitions_and_results_are_pushed_to_tournament_room(
    client, admin_headers, db_session, open_tournament, spy
):
    await _teams(db_session, open_tournament, 2)
    await _close(client, admin_headers, open_tournament)
    await _start(client, admin_headers, open_tournament)
    (match,) = await _matches(client, open_tournament)
    await _result(client, admin_headers, open_tournament, match, 1, 0)

    room = f"tournament:{open_tournament.id}"
    assert {r for r, _ in spy["broadcast"]} == {room}
    events = [(p["event"], p["data"].get("status")) for _, p in spy["broadcast"]]
    assert events == [
        ("status_changed", "registration_closed"),
        ("status_changed", "running"),
        ("match_updated", "completed"),
        ("status_changed", "finished"),
    ]


@pytest.mark.asyncio
async def test_eliminated_team_members_are_revoked_from_chat(
    client, admin_headers, db_session, open_tournament, spy
):
    await create_team(db_session, open_tournament, "Win")
    loser, loser_users = await create_team(db_session, open_tournament, "Lose")
    await _close(client, admin_headers, open_tournament)
    await _start(client, admin_headers, open_tournament)
    (match,) = await _matches(client, open_tournament)
    await _result(client, admin_headers, open_tournament, match, 3, 0)

    assert {(room, uid) for room, uid, _ in spy["revoke"]} == {
        (f"team:{loser.id}", u.id) for u in loser_users
    }
    assert {reason for *_, reason in spy["revoke"]} == {"eliminated"}
