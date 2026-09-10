"""Security tests -- per-team exchange space (chat).

Covers the access rules in ``context.md`` section 8 for reading and posting to
a team's private chat (B-16, B-17, B-18):

- read: caller is a current member of that team, OR admin
- post: caller is a current member AND the team is not eliminated
- an excluded member loses access immediately (B-17)
- an eliminated team's space is closed to members; admin keeps read access (B-18)

These are the REST guards. The WebSocket room (``team:<id>``) enforces the same
checks on connect and per message; realtime coverage lives with the realtime
module, not here.

V0: provisional REST shape; tests report as skipped until the ``client``
fixture is wired to the app.
"""

# --- Read: non-members are refused --------------------------------------


def test_read_chat_denied_when_not_a_member(client, auth, other_player_token, team):
    resp = client.get(f"/teams/{team.id}/chat/messages", headers=auth(other_player_token))
    assert resp.status_code in (401, 403)


def test_read_chat_denied_when_anonymous(client, team):
    resp = client.get(f"/teams/{team.id}/chat/messages")
    assert resp.status_code in (401, 403)


def test_post_chat_denied_when_not_a_member(client, auth, other_player_token, team):
    resp = client.post(
        f"/teams/{team.id}/chat/messages",
        headers=auth(other_player_token),
        json={"body": "let me in"},
    )
    assert resp.status_code in (401, 403)


# --- Excluded member loses access immediately (B-17) -------------------


def test_read_chat_denied_when_member_excluded(client, auth, excluded_player_token, team):
    resp = client.get(f"/teams/{team.id}/chat/messages", headers=auth(excluded_player_token))
    assert resp.status_code in (401, 403)


def test_post_chat_denied_when_member_excluded(client, auth, excluded_player_token, team):
    resp = client.post(
        f"/teams/{team.id}/chat/messages",
        headers=auth(excluded_player_token),
        json={"body": "still here?"},
    )
    assert resp.status_code in (401, 403)


# --- Eliminated team: space closed to members, admin may read (B-18) --


def test_post_chat_denied_when_team_eliminated(client, auth, captain_token, eliminated_team):
    resp = client.post(
        f"/teams/{eliminated_team.id}/chat/messages",
        headers=auth(captain_token),
        json={"body": "gg"},
    )
    assert resp.status_code in (403, 409)


def test_read_chat_denied_when_team_eliminated_and_caller_is_member(
    client, auth, captain_token, eliminated_team
):
    resp = client.get(
        f"/teams/{eliminated_team.id}/chat/messages",
        headers=auth(captain_token),
    )
    assert resp.status_code in (403, 409)


# --- Positive stubs -----------------------------------------------------


def test_read_chat_allowed_when_current_member(client, auth, captain_token, team):
    resp = client.get(f"/teams/{team.id}/chat/messages", headers=auth(captain_token))
    assert resp.status_code == 200


def test_post_chat_allowed_when_current_member(client, auth, captain_token, team):
    resp = client.post(
        f"/teams/{team.id}/chat/messages",
        headers=auth(captain_token),
        json={"body": "scrim at 8"},
    )
    assert resp.status_code == 201


def test_read_chat_allowed_when_admin(client, auth, admin_token, team):
    """B-16: an admin may read any team chat."""
    resp = client.get(f"/teams/{team.id}/chat/messages", headers=auth(admin_token))
    assert resp.status_code == 200


def test_read_chat_allowed_when_admin_and_team_eliminated(
    client, auth, admin_token, eliminated_team
):
    """B-18: an admin can still read a closed (eliminated) team's chat."""
    resp = client.get(
        f"/teams/{eliminated_team.id}/chat/messages",
        headers=auth(admin_token),
    )
    assert resp.status_code == 200
