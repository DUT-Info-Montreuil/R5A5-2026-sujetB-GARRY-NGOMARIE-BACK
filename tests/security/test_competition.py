"""Security tests -- running the competition.

Covers the access rules in ``context.md`` section 8 for entering results and
declaring forfeits (B-13, B-14, B-15): admin only, tournament ``running``,
both teams of the match known. Viewing the bracket/progress is public (B-02).

V0: provisional REST shape; tests report as skipped until the ``client``
fixture is wired to the app.
"""

# --- Enter a match result --------------------------------------------------


def test_enter_result_denied_when_not_admin(client, auth, player_token, ready_match):
    resp = client.post(
        f"/matches/{ready_match.id}/result",
        headers=auth(player_token),
        json={"winner_team_id": 1},
    )
    assert resp.status_code in (401, 403)


def test_enter_result_denied_when_anonymous(client, ready_match):
    resp = client.post(f"/matches/{ready_match.id}/result", json={"winner_team_id": 1})
    assert resp.status_code in (401, 403)


def test_enter_result_denied_when_tournament_not_running(
    client, auth, admin_token, closed_tournament
):
    resp = client.post(
        f"/tournaments/{closed_tournament.id}/matches/1/result",
        headers=auth(admin_token),
        json={"winner_team_id": 1},
    )
    assert resp.status_code in (403, 409)


def test_enter_result_denied_when_both_teams_not_known(client, auth, admin_token, pending_match):
    """B-14: a match is playable only once both its teams are known."""
    resp = client.post(
        f"/matches/{pending_match.id}/result",
        headers=auth(admin_token),
        json={"winner_team_id": 1},
    )
    assert resp.status_code in (403, 409, 422)


# --- Declare a forfeit --------------------------------------------------


def test_declare_forfeit_denied_when_not_admin(client, auth, player_token, ready_match):
    resp = client.post(
        f"/matches/{ready_match.id}/forfeit",
        headers=auth(player_token),
        json={"forfeiting_team_id": 1},
    )
    assert resp.status_code in (401, 403)


def test_declare_forfeit_denied_when_tournament_not_running(
    client, auth, admin_token, closed_tournament
):
    resp = client.post(
        f"/tournaments/{closed_tournament.id}/matches/1/forfeit",
        headers=auth(admin_token),
        json={"forfeiting_team_id": 1},
    )
    assert resp.status_code in (403, 409)


# --- Positive stubs -----------------------------------------------------


def test_enter_result_allowed_when_admin_and_running(client, auth, admin_token, ready_match):
    resp = client.post(
        f"/matches/{ready_match.id}/result",
        headers=auth(admin_token),
        json={"winner_team_id": 1},
    )
    assert resp.status_code == 200


def test_declare_forfeit_allowed_when_admin_and_running(client, auth, admin_token, ready_match):
    resp = client.post(
        f"/matches/{ready_match.id}/forfeit",
        headers=auth(admin_token),
        json={"forfeiting_team_id": 1},
    )
    assert resp.status_code == 200


def test_view_bracket_allowed_when_anonymous(client, running_tournament):
    """B-02 / B-19: bracket and progress are public."""
    resp = client.get(f"/tournaments/{running_tournament.id}/bracket")
    assert resp.status_code == 200
