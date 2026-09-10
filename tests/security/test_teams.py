"""Security tests -- team formation and composition.

Covers the access rules in ``context.md`` section 8 for creating, joining and
leaving teams and for captain-only composition changes (B-05 .. B-11):

- one team per player per tournament (B-07)
- 5-player roster cap (B-08)
- captain-of-that-team ownership check on every mutation (B-09, B-10)
- roster/roles immutable once registration is closed (B-11)

V0: provisional REST shape; tests report as skipped until the ``client``
fixture is wired to the app.
"""

# --- Create team ----------------------------------------------------------


def test_create_team_denied_when_anonymous(client, open_tournament):
    resp = client.post(f"/tournaments/{open_tournament.id}/teams", json={"name": "Alpha"})
    assert resp.status_code in (401, 403)


def test_create_team_denied_when_already_in_a_team_this_tournament(
    client, auth, captain_token, open_tournament
):
    """B-07: a player is in at most one team per tournament."""
    resp = client.post(
        f"/tournaments/{open_tournament.id}/teams",
        headers=auth(captain_token),
        json={"name": "Second Team"},
    )
    assert resp.status_code in (403, 409)


def test_create_team_denied_when_registration_closed(client, auth, player_token, closed_tournament):
    resp = client.post(
        f"/tournaments/{closed_tournament.id}/teams",
        headers=auth(player_token),
        json={"name": "Latecomer"},
    )
    assert resp.status_code in (403, 409)


# --- Join team ----------------------------------------------------------


def test_join_team_denied_when_team_full(client, auth, player_token, full_team):
    """B-08: a 6th member is refused."""
    resp = client.post(
        f"/teams/{full_team.id}/members",
        headers=auth(player_token),
        json={"role": "duelist"},
    )
    assert resp.status_code in (403, 409)


def test_join_team_denied_when_already_in_another_team_this_tournament(
    client, auth, other_player_token, team
):
    """B-07: cannot join a second team in the same tournament."""
    resp = client.post(
        f"/teams/{team.id}/members",
        headers=auth(other_player_token),
        json={"role": "duelist"},
    )
    assert resp.status_code in (403, 409)


def test_join_team_denied_when_registration_closed(client, auth, player_token, closed_tournament):
    resp = client.post(
        f"/tournaments/{closed_tournament.id}/teams/1/members",
        headers=auth(player_token),
        json={"role": "duelist"},
    )
    assert resp.status_code in (403, 409)


# --- Leave team ----------------------------------------------------------


def test_leave_team_denied_when_not_a_member(client, auth, other_player_token, team):
    resp = client.delete(f"/teams/{team.id}/members/me", headers=auth(other_player_token))
    assert resp.status_code in (401, 403)


def test_leave_team_denied_when_registration_closed(client, auth, captain_token, closed_tournament):
    resp = client.delete(
        f"/tournaments/{closed_tournament.id}/teams/1/members/me",
        headers=auth(captain_token),
    )
    assert resp.status_code in (403, 409)


# --- Captain-only composition changes: wrong caller (B-09, B-10) --------


def test_rename_team_denied_when_not_captain(client, auth, other_player_token, team):
    resp = client.patch(
        f"/teams/{team.id}",
        headers=auth(other_player_token),
        json={"name": "Hijacked"},
    )
    assert resp.status_code in (401, 403)


def test_assign_role_denied_when_not_captain(client, auth, player_token, team):
    resp = client.put(
        f"/teams/{team.id}/members/2/role",
        headers=auth(player_token),
        json={"role": "sentinel"},
    )
    assert resp.status_code in (401, 403)


def test_exclude_member_denied_when_not_captain(client, auth, other_player_token, team):
    resp = client.delete(f"/teams/{team.id}/members/2", headers=auth(other_player_token))
    assert resp.status_code in (401, 403)


def test_transfer_captaincy_denied_when_not_captain(client, auth, player_token, team):
    resp = client.post(
        f"/teams/{team.id}/captain",
        headers=auth(player_token),
        json={"user_id": 2},
    )
    assert resp.status_code in (401, 403)


# --- Composition frozen after registration close (B-11) ----------------


def test_rename_team_denied_when_registration_closed(
    client, auth, captain_token, closed_tournament
):
    resp = client.patch(
        f"/tournaments/{closed_tournament.id}/teams/1",
        headers=auth(captain_token),
        json={"name": "Too Late"},
    )
    assert resp.status_code in (403, 409)


def test_assign_role_denied_when_registration_closed(
    client, auth, captain_token, closed_tournament
):
    resp = client.put(
        f"/tournaments/{closed_tournament.id}/teams/1/members/2/role",
        headers=auth(captain_token),
        json={"role": "sentinel"},
    )
    assert resp.status_code in (403, 409)


def test_exclude_member_denied_when_registration_closed(
    client, auth, captain_token, closed_tournament
):
    resp = client.delete(
        f"/tournaments/{closed_tournament.id}/teams/1/members/2",
        headers=auth(captain_token),
    )
    assert resp.status_code in (403, 409)


def test_transfer_captaincy_denied_when_registration_closed(
    client, auth, captain_token, closed_tournament
):
    resp = client.post(
        f"/tournaments/{closed_tournament.id}/teams/1/captain",
        headers=auth(captain_token),
        json={"user_id": 2},
    )
    assert resp.status_code in (403, 409)


# --- Positive stubs: the authorized caller succeeds --------------------


def test_create_team_allowed_when_player_and_registration_open(
    client, auth, player_token, open_tournament
):
    resp = client.post(
        f"/tournaments/{open_tournament.id}/teams",
        headers=auth(player_token),
        json={"name": "Alpha", "role": "duelist"},
    )
    assert resp.status_code == 201


def test_join_team_allowed_when_slot_available_and_registration_open(
    client, auth, player_token, team
):
    resp = client.post(
        f"/teams/{team.id}/members",
        headers=auth(player_token),
        json={"role": "duelist"},
    )
    assert resp.status_code in (200, 201)


def test_leave_team_allowed_when_member_and_registration_open(client, auth, player_token, team):
    resp = client.delete(f"/teams/{team.id}/members/me", headers=auth(player_token))
    assert resp.status_code in (200, 204)


def test_rename_team_allowed_when_captain_and_registration_open(client, auth, captain_token, team):
    resp = client.patch(
        f"/teams/{team.id}",
        headers=auth(captain_token),
        json={"name": "Alpha Squad"},
    )
    assert resp.status_code == 200


def test_transfer_captaincy_allowed_when_captain(client, auth, captain_token, team):
    resp = client.post(
        f"/teams/{team.id}/captain",
        headers=auth(captain_token),
        json={"user_id": 2},
    )
    assert resp.status_code == 200
