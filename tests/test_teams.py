import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_password_hash
from app.models.entities import Tournament, User


async def create_user(
    db_session: AsyncSession, username: str, email: str, role: str = "player"
) -> User:
    user = User(
        id=uuid.uuid4(),
        username=username,
        email=email,
        hashed_password=get_password_hash("SecretPass123!"),
        global_role=role,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def auth_header(user: User) -> dict[str, str]:
    token = create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.global_role}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def closed_tournament(db_session: AsyncSession, admin_user: User) -> Tournament:
    t = Tournament(
        id=uuid.uuid4(),
        name="Tournament Closed",
        game="Valorant",
        status="registration_closed",
        created_by=admin_user.id,
    )
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


# =============================================================================
# Création d'équipe
# =============================================================================
@pytest.mark.asyncio
async def test_player_can_create_team_and_becomes_captain(
    client: AsyncClient,
    open_tournament: Tournament,
    player_user: User,
    player_headers: dict[str, str],
):
    """Un joueur crée une équipe et devient son capitaine."""
    payload = {"name": "Karmine Corp", "game_role": "Duelist"}
    resp = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json=payload,
        headers=player_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Karmine Corp"
    assert data["captain_id"] == str(player_user.id)
    assert data["members_count"] == 1
    assert data["members"][0]["user_id"] == str(player_user.id)
    assert data["members"][0]["game_role"] == "Duelist"
    assert "id" in data


@pytest.mark.asyncio
async def test_cannot_create_team_when_registration_closed(
    client: AsyncClient,
    closed_tournament: Tournament,
    player_headers: dict[str, str],
):
    """Roster/équipes ne changent pas si inscription fermée."""
    resp = await client.post(
        f"/api/v1/tournaments/{closed_tournament.id}/teams",
        json={"name": "Solary", "game_role": "Initiator"},
        headers=player_headers,
    )
    assert resp.status_code == 400
    assert "fermées" in resp.json()["detail"]


# =============================================================================
# Un joueur dans au plus UNE équipe par tournoi
# =============================================================================
@pytest.mark.asyncio
async def test_player_cannot_be_in_two_teams_in_same_tournament(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_user: User,
    player_headers: dict[str, str],
):
    # Créer une première équipe
    resp1 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Team One"},
        headers=player_headers,
    )
    assert resp1.status_code == 201

    # Tenter d'en créer une deuxième dans le même tournoi
    resp2 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Team Two"},
        headers=player_headers,
    )
    assert resp2.status_code == 409
    assert "déjà partie d'une équipe" in resp2.json()["detail"]

    # Créer une autre équipe par un autre joueur et tenter de la rejoindre
    other_user = await create_user(db_session, "other_p", "other@test.fr")
    resp_other = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Team Three"},
        headers=auth_header(other_user),
    )
    team3_id = resp_other.json()["id"]

    # player_user tente de rejoindre team3 -> Rejeté
    resp_join = await client.post(
        f"/api/v1/teams/{team3_id}/join",
        headers=player_headers,
    )
    assert resp_join.status_code == 409


@pytest.mark.asyncio
async def test_player_can_play_several_tournaments(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    admin_user: User,
    player_headers: dict[str, str],
):
    """Un joueur peut jouer dans plusieurs tournois distincts."""
    t2 = Tournament(
        id=uuid.uuid4(),
        name="Tournament 2",
        game="LoL",
        status="registration_open",
        created_by=admin_user.id,
    )
    db_session.add(t2)
    await db_session.commit()

    resp1 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Team Tourn 1"},
        headers=player_headers,
    )
    assert resp1.status_code == 201

    resp2 = await client.post(
        f"/api/v1/tournaments/{t2.id}/teams",
        json={"name": "Team Tourn 2"},
        headers=player_headers,
    )
    assert resp2.status_code == 201


# =============================================================================
# Demande d'adhésion, Approbation Capitaine, Quitter, et Limite à 5
# =============================================================================
@pytest.mark.asyncio
async def test_join_request_flow_and_captain_approval(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    """Demander à rejoindre une équipe + approbation par le capitaine."""
    # 1. Capitaine crée l'équipe
    resp_team = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Approval Squad"},
        headers=player_headers,
    )
    team_id = resp_team.json()["id"]

    # 2. Joueur demande à rejoindre
    candidate = await create_user(db_session, "candidate_1", "cand1@test.fr")
    candidate_headers = auth_header(candidate)

    req_resp = await client.post(
        f"/api/v1/teams/{team_id}/join",
        json={"game_role": "Initiator"},
        headers=candidate_headers,
    )
    assert req_resp.status_code == 202
    req_data = req_resp.json()
    assert req_data["status"] == "pending"
    req_id = req_data["id"]

    # 3. Capitaine consulte les demandes d'adhésion
    requests_list = await client.get(
        f"/api/v1/teams/{team_id}/join-requests",
        headers=player_headers,
    )
    assert requests_list.status_code == 200
    assert len(requests_list.json()) == 1
    assert requests_list.json()[0]["id"] == req_id

    # 4. Tenter d'accepter en tant que non-capitaine -> 403
    forbidden_resp = await client.post(
        f"/api/v1/teams/{team_id}/join-requests/{req_id}/accept",
        headers=candidate_headers,
    )
    assert forbidden_resp.status_code == 403

    # 5. Capitaine accepte la demande
    accept_resp = await client.post(
        f"/api/v1/teams/{team_id}/join-requests/{req_id}/accept",
        headers=player_headers,
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["members_count"] == 2
    assert any(m["user_id"] == str(candidate.id) for m in accept_resp.json()["members"])


@pytest.mark.asyncio
async def test_team_max_5_players(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    # Création équipe avec capitaine (1 joueur)
    resp = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Penta Squad"},
        headers=player_headers,
    )
    team_id = resp.json()["id"]

    # Ajouter 4 joueurs (total 5) via demandes acceptées par le capitaine
    for i in range(2, 6):
        u = await create_user(db_session, f"player_{i}", f"player_{i}@test.fr")
        req_res = await client.post(
            f"/api/v1/teams/{team_id}/join", headers=auth_header(u)
        )
        assert req_res.status_code == 202
        req_id = req_res.json()["id"]
        acc_res = await client.post(
            f"/api/v1/teams/{team_id}/join-requests/{req_id}/accept",
            headers=player_headers,
        )
        assert acc_res.status_code == 200

    # Vérifier que l'équipe a 5 membres
    team_info = await client.get(f"/api/v1/teams/{team_id}")
    assert team_info.json()["members_count"] == 5

    # Le 6ème joueur tente de demander à rejoindre -> Rejeté 400 Bad Request
    u6 = await create_user(db_session, "player_6", "player_6@test.fr")
    r6 = await client.post(f"/api/v1/teams/{team_id}/join", headers=auth_header(u6))
    assert r6.status_code == 400
    assert "complète" in r6.json()["detail"]


@pytest.mark.asyncio
async def test_player_can_leave_team_while_open(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    # Capitaine crée l'équipe
    resp = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Leaving Squad"},
        headers=player_headers,
    )
    team_id = resp.json()["id"]

    # Membre 2 demande et est accepté
    m2 = await create_user(db_session, "member_2", "m2@test.fr")
    m2_headers = auth_header(m2)
    req_res = await client.post(f"/api/v1/teams/{team_id}/join", headers=m2_headers)
    assert req_res.status_code == 202
    await client.post(
        f"/api/v1/teams/{team_id}/join-requests/{req_res.json()['id']}/accept",
        headers=player_headers,
    )

    # Membre 2 quitte
    leave_resp = await client.post(f"/api/v1/teams/{team_id}/leave", headers=m2_headers)
    assert leave_resp.status_code == 200

    # Vérification: l'équipe n'a plus que 1 membre
    team_info = await client.get(f"/api/v1/teams/{team_id}")
    assert team_info.json()["members_count"] == 1


# =============================================================================
# Actions réservées au capitaine
# =============================================================================
@pytest.mark.asyncio
async def test_captain_controls_and_non_captain_refused(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    # Création équipe par player_user (capitaine)
    resp = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Initial Name"},
        headers=player_headers,
    )
    team_id = resp.json()["id"]

    # Un joueur tiers non capitaine
    non_captain = await create_user(db_session, "non_cap", "noncap@test.fr")
    nc_headers = auth_header(non_captain)
    nc_req = await client.post(f"/api/v1/teams/{team_id}/join", headers=nc_headers)
    assert nc_req.status_code == 202
    await client.post(
        f"/api/v1/teams/{team_id}/join-requests/{nc_req.json()['id']}/accept",
        headers=player_headers,
    )

    team_data = (await client.get(f"/api/v1/teams/{team_id}")).json()
    nc_member_id = next(
        m["id"] for m in team_data["members"] if m["username"] == "non_cap"
    )

    # 1. Renommer l'équipe
    # Refusé pour non-capitaine (403)
    r_rename_fail = await client.patch(
        f"/api/v1/teams/{team_id}/name",
        json={"name": "Hacked Name"},
        headers=nc_headers,
    )
    assert r_rename_fail.status_code == 403

    # Accepté pour capitaine (200)
    r_rename_ok = await client.patch(
        f"/api/v1/teams/{team_id}/name",
        json={"name": "Updated Name"},
        headers=player_headers,
    )
    assert r_rename_ok.status_code == 200
    assert r_rename_ok.json()["name"] == "Updated Name"

    # 2. Assigner un rôle
    # Refusé pour non-capitaine (403)
    r_role_fail = await client.patch(
        f"/api/v1/teams/{team_id}/members/{nc_member_id}/role",
        json={"game_role": "Support"},
        headers=nc_headers,
    )
    assert r_role_fail.status_code == 403

    # Accepté pour capitaine (200)
    r_role_ok = await client.patch(
        f"/api/v1/teams/{team_id}/members/{nc_member_id}/role",
        json={"game_role": "Support"},
        headers=player_headers,
    )
    assert r_role_ok.status_code == 200

    # 3. Transférer le capitanat
    r_transfer = await client.post(
        f"/api/v1/teams/{team_id}/transfer-captain",
        json={"new_captain_id": str(non_captain.id)},
        headers=player_headers,
    )
    assert r_transfer.status_code == 200
    assert r_transfer.json()["captain_id"] == str(non_captain.id)

    # L'ancien capitaine ne peut plus exclure
    r_exclude_fail = await client.delete(
        f"/api/v1/teams/{team_id}/members/{nc_member_id}",
        headers=player_headers,
    )
    assert r_exclude_fail.status_code == 403

    # Le nouveau capitaine peut exclure l'ancien
    team_data2 = (await client.get(f"/api/v1/teams/{team_id}")).json()
    old_cap_member_id = next(
        m["id"] for m in team_data2["members"] if m["username"] == "player_test"
    )
    r_exclude_ok = await client.delete(
        f"/api/v1/teams/{team_id}/members/{old_cap_member_id}",
        headers=nc_headers,
    )
    assert r_exclude_ok.status_code == 200
    assert r_exclude_ok.json()["members_count"] == 1


# =============================================================================
# Roster et rôles gelés après fermeture des inscriptions
# =============================================================================
@pytest.mark.asyncio
async def test_frozen_roster_after_close(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    # Créer équipe
    resp = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Frozen Squad"},
        headers=player_headers,
    )
    team_id = resp.json()["id"]

    # Simuler fermeture des inscriptions (statut = registration_closed)
    open_tournament.status = "registration_closed"
    await db_session.commit()

    # Tenter de renommer
    r1 = await client.patch(
        f"/api/v1/teams/{team_id}/name",
        json={"name": "New Name"},
        headers=player_headers,
    )
    assert r1.status_code == 400
    assert "fermées" in r1.json()["detail"]

    # Tenter de quitter
    r2 = await client.post(
        f"/api/v1/teams/{team_id}/leave",
        headers=player_headers,
    )
    assert r2.status_code == 400
    assert "fermées" in r2.json()["detail"]
