"""Security tests -- tournament administration.

Covers the access rules in ``context.md`` section 8 for tournament creation
and state transitions (B-01, B-02, B-03, B-04) and the ``< 2 engaged teams``
guard on closing registration.

V0: bodies are written against a provisional REST shape; endpoint paths will
be confirmed when the routers land. Every test currently reports as skipped
because the ``client`` fixture has no app to bind to yet.
"""

# --- Negative: only an admin creates or pilots a tournament ---------------


def test_create_tournament_denied_when_not_admin(client, auth, player_token):
    resp = client.post(
        "/tournaments",
        headers=auth(player_token),
        json={"name": "Spring Cup", "game": "Valorant"},
    )
    assert resp.status_code in (401, 403)


def test_create_tournament_denied_when_anonymous(client):
    resp = client.post("/tournaments", json={"name": "Spring Cup", "game": "Valorant"})
    assert resp.status_code in (401, 403)


def test_open_registration_denied_when_not_admin(client, auth, player_token, closed_tournament):
    resp = client.post(
        f"/tournaments/{closed_tournament.id}/registration/open",
        headers=auth(player_token),
    )
    assert resp.status_code in (401, 403)


def test_close_registration_denied_when_not_admin(client, auth, player_token, open_tournament):
    resp = client.post(
        f"/tournaments/{open_tournament.id}/registration/close",
        headers=auth(player_token),
    )
    assert resp.status_code in (401, 403)


def test_start_tournament_denied_when_not_admin(client, auth, player_token, closed_tournament):
    resp = client.post(
        f"/tournaments/{closed_tournament.id}/start",
        headers=auth(player_token),
    )
    assert resp.status_code in (401, 403)


def test_close_registration_denied_when_fewer_than_two_engaged_teams(
    client, auth, admin_token, single_team_tournament
):
    """context.md section 8: cannot form a bracket with < 2 engaged teams."""
    resp = client.post(
        f"/tournaments/{single_team_tournament.id}/registration/close",
        headers=auth(admin_token),
    )
    assert resp.status_code == 422


def test_start_tournament_denied_when_registration_still_open(
    client, auth, admin_token, open_tournament
):
    resp = client.post(
        f"/tournaments/{open_tournament.id}/start",
        headers=auth(admin_token),
    )
    assert resp.status_code in (409, 422)


# --- Positive stubs: the authorized caller succeeds (B-01, B-02) --------


def test_create_tournament_allowed_when_admin(client, auth, admin_token):
    resp = client.post(
        "/tournaments",
        headers=auth(admin_token),
        json={"name": "Spring Cup", "game": "Valorant"},
    )
    assert resp.status_code == 201


def test_view_tournament_allowed_when_anonymous(client, open_tournament):
    """B-02: anyone, including unauthenticated callers, can view a tournament."""
    resp = client.get(f"/tournaments/{open_tournament.id}")
    assert resp.status_code == 200


def test_close_registration_allowed_when_admin_and_two_teams(
    client, auth, admin_token, open_tournament
):
    resp = client.post(
        f"/tournaments/{open_tournament.id}/registration/close",
        headers=auth(admin_token),
    )
    assert resp.status_code == 200
