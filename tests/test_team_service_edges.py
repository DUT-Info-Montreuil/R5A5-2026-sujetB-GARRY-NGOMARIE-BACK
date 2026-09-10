import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_password_hash
from app.models.entities import TeamJoinRequest, TeamMember, Tournament, User


@pytest.mark.asyncio
async def test_list_teams_and_search(
    client: AsyncClient,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    # Créer 2 équipes
    r1 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Alpha Squad"},
        headers=player_headers,
    )
    assert r1.status_code == 201

    # Créer un second joueur pour créer une 2ème équipe
    # (via register)
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "creator_two",
            "email": "c2@example.com",
            "password": "Password123!",
            "global_role": "player",
        },
    )
    user2_id = reg.json()["id"]
    t2 = create_access_token(
        {"sub": user2_id, "username": "creator_two", "role": "player"}
    )
    h2 = {"Authorization": f"Bearer {t2}"}

    r2 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Beta Squad"},
        headers=h2,
    )
    assert r2.status_code == 201

    # List sans search
    res_all = await client.get(f"/api/v1/tournaments/{open_tournament.id}/teams")
    assert res_all.status_code == 200
    assert len(res_all.json()) >= 2

    # List avec search matchant "Alpha"
    res_search = await client.get(
        f"/api/v1/tournaments/{open_tournament.id}/teams?search=Alpha"
    )
    assert res_search.status_code == 200
    assert len(res_search.json()) == 1
    assert res_search.json()[0]["name"] == "Alpha Squad"

    # List avec search ne matchant rien
    res_none = await client.get(
        f"/api/v1/tournaments/{open_tournament.id}/teams?search=Gamma"
    )
    assert res_none.status_code == 200
    assert len(res_none.json()) == 0

    # 404 sur tournoi inexistant
    res_404 = await client.get(f"/api/v1/tournaments/{uuid.uuid4()}/teams")
    assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_team_crud_and_name_conflict(
    client: AsyncClient,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    tourn_id = str(open_tournament.id)

    # Créer équipe 1
    r1 = await client.post(
        f"/api/v1/tournaments/{tourn_id}/teams",
        json={"name": "Original Team"},
        headers=player_headers,
    )
    assert r1.status_code == 201

    # 404 sur tournoi inexistant lors de création
    r_bad_tourn = await client.post(
        f"/api/v1/tournaments/{uuid.uuid4()}/teams",
        json={"name": "Bad Tourn Team"},
        headers=player_headers,
    )
    assert r_bad_tourn.status_code == 404

    # 404 get_team
    r_bad_team = await client.get(f"/api/v1/teams/{uuid.uuid4()}")
    assert r_bad_team.status_code == 404

    # Créer un 2ème joueur avec son équipe
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "p_two",
            "email": "ptwo@example.com",
            "password": "Password123!",
            "global_role": "player",
        },
    )
    t2 = create_access_token(
        {"sub": reg.json()["id"], "username": "p_two", "role": "player"}
    )
    h2 = {"Authorization": f"Bearer {t2}"}

    # Tentative de créer une équipe avec un nom déjà existant -> 409
    r_dup = await client.post(
        f"/api/v1/tournaments/{tourn_id}/teams",
        json={"name": "Original Team"},
        headers=h2,
    )
    assert r_dup.status_code == 409

    # Créer avec un nom unique
    r2 = await client.post(
        f"/api/v1/tournaments/{tourn_id}/teams",
        json={"name": "Second Team"},
        headers=h2,
    )
    assert r2.status_code == 201
    team2_id = r2.json()["id"]

    # Renommer Team 2 vers "Original Team" -> 409
    r_dup_rename = await client.patch(
        f"/api/v1/teams/{team2_id}/name",
        json={"name": "Original Team"},
        headers=h2,
    )
    assert r_dup_rename.status_code == 409


@pytest.mark.asyncio
async def test_join_request_edge_cases(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    # Equipe
    r1 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Join Squad"},
        headers=player_headers,
    )
    team_id = r1.json()["id"]

    # Joueur candidat
    candidate = User(
        id=uuid.uuid4(),
        username="candidate_1",
        email="c1@test.local",
        hashed_password=get_password_hash("pass"),
        global_role="player",
    )
    db_session.add(candidate)
    await db_session.commit()
    c_token = create_access_token(
        {"sub": str(candidate.id), "username": "candidate_1", "role": "player"}
    )
    c_headers = {"Authorization": f"Bearer {c_token}"}

    # 404 sur join d'une team inexistante
    r_join_404 = await client.post(
        f"/api/v1/teams/{uuid.uuid4()}/join",
        json={"game_role": "DPS"},
        headers=c_headers,
    )
    assert r_join_404.status_code == 404

    # Envoi d'une demande valide
    r_join_ok = await client.post(
        f"/api/v1/teams/{team_id}/join",
        json={"game_role": "DPS"},
        headers=c_headers,
    )
    assert r_join_ok.status_code == 202
    req_id = r_join_ok.json()["id"]

    # Tentative d'envoyer une seconde demande en attente pour la même équipe -> 409
    r_join_dup = await client.post(
        f"/api/v1/teams/{team_id}/join",
        json={"game_role": "Tank"},
        headers=c_headers,
    )
    assert r_join_dup.status_code == 409

    # Liste join requests par non capitaine -> 403
    r_list_nc = await client.get(
        f"/api/v1/teams/{team_id}/join-requests",
        headers=c_headers,
    )
    assert r_list_nc.status_code == 403

    # Répondre avec action invalide -> 400
    r_bad_action = await client.post(
        f"/api/v1/teams/{team_id}/join-requests/{req_id}/invalid_action",
        headers=player_headers,
    )
    assert r_bad_action.status_code == 400

    # Répondre sur demande inexistante -> 404
    r_req_404 = await client.post(
        f"/api/v1/teams/{team_id}/join-requests/{uuid.uuid4()}/accept",
        headers=player_headers,
    )
    assert r_req_404.status_code == 404

    # Rejet d'une demande valide (action = "reject")
    r_reject = await client.post(
        f"/api/v1/teams/{team_id}/join-requests/{req_id}/reject",
        headers=player_headers,
    )
    assert r_reject.status_code == 200

    # Tenter de ré-accepter une demande déjà traitée -> 400
    r_reaccept = await client.post(
        f"/api/v1/teams/{team_id}/join-requests/{req_id}/accept",
        headers=player_headers,
    )
    assert r_reaccept.status_code == 400


@pytest.mark.asyncio
async def test_join_request_multi_pending_and_already_joined(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    # Créer Team 1
    r1 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Multi Team 1"},
        headers=player_headers,
    )
    team1_id = r1.json()["id"]

    # Créer Team 2 avec Captain 2
    c2 = User(
        id=uuid.uuid4(),
        username="captain_2",
        email="cap2@test.local",
        hashed_password=get_password_hash("pass"),
        global_role="player",
    )
    db_session.add(c2)
    await db_session.commit()
    t_c2 = create_access_token(
        {"sub": str(c2.id), "username": "captain_2", "role": "player"}
    )
    h_c2 = {"Authorization": f"Bearer {t_c2}"}

    r2 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Multi Team 2"},
        headers=h_c2,
    )
    team2_id = r2.json()["id"]

    # Candidat qui postule à Team 1 ET à Team 2
    candidate = User(
        id=uuid.uuid4(),
        username="multi_candidate",
        email="multi@test.local",
        hashed_password=get_password_hash("pass"),
        global_role="player",
    )
    db_session.add(candidate)
    await db_session.commit()
    t_cand = create_access_token(
        {"sub": str(candidate.id), "username": "multi_candidate", "role": "player"}
    )
    h_cand = {"Authorization": f"Bearer {t_cand}"}

    # Demande pour team 1
    req1 = (await client.post(f"/api/v1/teams/{team1_id}/join", headers=h_cand)).json()
    # Demande pour team 2
    req2 = (await client.post(f"/api/v1/teams/{team2_id}/join", headers=h_cand)).json()

    # Captain 1 accepte candidate dans Team 1
    acc1 = await client.post(
        f"/api/v1/teams/{team1_id}/join-requests/{req1['id']}/accept",
        headers=player_headers,
    )
    assert acc1.status_code == 200

    # L'autre demande pour Team 2 a dû être automatiquement rejetée
    req2_db = await db_session.get(TeamJoinRequest, uuid.UUID(req2["id"]))
    await db_session.refresh(req2_db)
    assert req2_db.status == "rejected"

    # Si Captain 2 tente d'accepter une demande alors que le joueur est déjà membre -> 409
    # Créons artificiellement une demande pending pour le joueur déjà membre
    dummy_req = TeamJoinRequest(
        team_id=uuid.UUID(team2_id),
        user_id=candidate.id,
        tournament_id=open_tournament.id,
        status="pending",
    )
    db_session.add(dummy_req)
    await db_session.commit()

    res_conflict = await client.post(
        f"/api/v1/teams/{team2_id}/join-requests/{dummy_req.id}/accept",
        headers=h_c2,
    )
    assert res_conflict.status_code == 409


@pytest.mark.asyncio
async def test_join_request_when_tournament_closed(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    r1 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Close Squad"},
        headers=player_headers,
    )
    team_id = r1.json()["id"]

    cand = User(
        id=uuid.uuid4(),
        username="late_cand",
        email="late@test.local",
        hashed_password=get_password_hash("pass"),
        global_role="player",
    )
    db_session.add(cand)
    await db_session.commit()
    t_cand = create_access_token(
        {"sub": str(cand.id), "username": "late_cand", "role": "player"}
    )
    h_cand = {"Authorization": f"Bearer {t_cand}"}

    # Créer une demande en attente
    r_join = await client.post(f"/api/v1/teams/{team_id}/join", headers=h_cand)
    req_id = r_join.json()["id"]

    # Fermer le tournoi
    open_tournament.status = "registration_closed"
    await db_session.commit()

    # Tenter de demander à rejoindre quand tournoi fermé -> 400
    r_late_join = await client.post(f"/api/v1/teams/{team_id}/join", headers=h_cand)
    assert r_late_join.status_code == 400

    # Tenter d'accepter quand tournoi fermé -> 400
    r_late_accept = await client.post(
        f"/api/v1/teams/{team_id}/join-requests/{req_id}/accept",
        headers=player_headers,
    )
    assert r_late_accept.status_code == 400


@pytest.mark.asyncio
async def test_team_leave_and_member_actions_edges(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    # Créer équipe (capitaine seul)
    r1 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Solo Team"},
        headers=player_headers,
    )
    team_id = r1.json()["id"]

    # Non membre tente de quitter -> 404
    other_u = User(
        id=uuid.uuid4(),
        username="non_member",
        email="nm@test.local",
        hashed_password=get_password_hash("pass"),
        global_role="player",
    )
    db_session.add(other_u)
    await db_session.commit()
    t_nm = create_access_token(
        {"sub": str(other_u.id), "username": "non_member", "role": "player"}
    )
    h_nm = {"Authorization": f"Bearer {t_nm}"}

    r_nm_leave = await client.post(f"/api/v1/teams/{team_id}/leave", headers=h_nm)
    assert r_nm_leave.status_code == 404

    # Assigner rôle à membre non existant -> 404
    r_role_404 = await client.patch(
        f"/api/v1/teams/{team_id}/members/{uuid.uuid4()}/role",
        json={"game_role": "Healer"},
        headers=player_headers,
    )
    assert r_role_404.status_code == 404

    # Exclure membre non existant -> 404
    r_exc_404 = await client.delete(
        f"/api/v1/teams/{team_id}/members/{uuid.uuid4()}",
        headers=player_headers,
    )
    assert r_exc_404.status_code == 404

    # Capitaine tente de s'auto-exclure -> 400
    team_data = (await client.get(f"/api/v1/teams/{team_id}")).json()
    cap_member_id = team_data["members"][0]["id"]
    r_self_exc = await client.delete(
        f"/api/v1/teams/{team_id}/members/{cap_member_id}",
        headers=player_headers,
    )
    assert r_self_exc.status_code == 400

    # Transférer capitanat à un utilisateur qui n'est pas dans l'équipe -> 400
    r_trans_bad = await client.post(
        f"/api/v1/teams/{team_id}/transfer-captain",
        json={"new_captain_id": str(other_u.id)},
        headers=player_headers,
    )
    assert r_trans_bad.status_code == 400

    # Capitaine seul quitte l'équipe -> dissolution
    r_leave_dissolve = await client.post(
        f"/api/v1/teams/{team_id}/leave",
        headers=player_headers,
    )
    assert r_leave_dissolve.status_code == 200
    assert "dissoute" in r_leave_dissolve.json()["message"]


@pytest.mark.asyncio
async def test_team_captain_cannot_leave_with_members(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    # Créer équipe
    r1 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Duo Team"},
        headers=player_headers,
    )
    team_id = r1.json()["id"]

    # Ajouter un second membre directement
    u2 = User(
        id=uuid.uuid4(),
        username="m2",
        email="m2@test.local",
        hashed_password=get_password_hash("pass"),
        global_role="player",
    )
    db_session.add(u2)
    m2 = TeamMember(
        team_id=uuid.UUID(team_id),
        user_id=u2.id,
        tournament_id=open_tournament.id,
        game_role="Support",
    )
    db_session.add(m2)
    await db_session.commit()

    # Capitaine essaie de quitter alors qu'il y a un autre membre -> 400
    r_cap_leave = await client.post(
        f"/api/v1/teams/{team_id}/leave",
        headers=player_headers,
    )
    assert r_cap_leave.status_code == 400
    assert "transférer son capitanat" in r_cap_leave.json()["detail"]


@pytest.mark.asyncio
async def test_accept_join_request_team_full(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    # Créer équipe (1 joueur)
    r1 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Full Squad Test"},
        headers=player_headers,
    )
    team_id = r1.json()["id"]

    # Ajouter 4 membres (total 5)
    for i in range(4):
        u = User(
            id=uuid.uuid4(),
            username=f"filler_{i}",
            email=f"filler_{i}@test.local",
            hashed_password=get_password_hash("pass"),
            global_role="player",
        )
        db_session.add(u)
        m = TeamMember(
            team_id=uuid.UUID(team_id),
            user_id=u.id,
            tournament_id=open_tournament.id,
            game_role="Flex",
        )
        db_session.add(m)

    # 6ème utilisateur qui a une demande pending
    u6 = User(
        id=uuid.uuid4(),
        username="sixth_user",
        email="sixth@test.local",
        hashed_password=get_password_hash("pass"),
        global_role="player",
    )
    db_session.add(u6)
    req = TeamJoinRequest(
        team_id=uuid.UUID(team_id),
        user_id=u6.id,
        tournament_id=open_tournament.id,
        status="pending",
    )
    db_session.add(req)
    await db_session.commit()

    # Le capitaine tente d'accepter la 6ème demande -> 400
    r_acc = await client.post(
        f"/api/v1/teams/{team_id}/join-requests/{req.id}/accept",
        headers=player_headers,
    )
    assert r_acc.status_code == 400
    assert "complète" in r_acc.json()["detail"]


@pytest.mark.asyncio
async def test_closed_guards_and_non_captain_transfer(
    client: AsyncClient,
    db_session: AsyncSession,
    open_tournament: Tournament,
    player_headers: dict[str, str],
):
    # Créer équipe
    r1 = await client.post(
        f"/api/v1/tournaments/{open_tournament.id}/teams",
        json={"name": "Guard Squad"},
        headers=player_headers,
    )
    team_id = r1.json()["id"]

    # Ajouter un second membre
    u2 = User(
        id=uuid.uuid4(),
        username="guard_u2",
        email="gu2@example.com",
        hashed_password=get_password_hash("pass"),
        global_role="player",
    )
    db_session.add(u2)
    m2 = TeamMember(
        team_id=uuid.UUID(team_id),
        user_id=u2.id,
        tournament_id=open_tournament.id,
        game_role="Flex",
    )
    db_session.add(m2)
    await db_session.commit()
    t2 = create_access_token(
        {"sub": str(u2.id), "username": "guard_u2", "role": "player"}
    )
    h2 = {"Authorization": f"Bearer {t2}"}

    # Non-capitaine tente de transférer le capitanat -> 403
    r_trans_nc = await client.post(
        f"/api/v1/teams/{team_id}/transfer-captain",
        json={"new_captain_id": str(u2.id)},
        headers=h2,
    )
    assert r_trans_nc.status_code == 403

    # Fermer le tournoi
    open_tournament.status = "registration_closed"
    await db_session.commit()

    # 1. Assigner rôle après fermeture -> 400
    r_role_closed = await client.patch(
        f"/api/v1/teams/{team_id}/members/{m2.id}/role",
        json={"game_role": "Captain"},
        headers=player_headers,
    )
    assert r_role_closed.status_code == 400
    assert "fermées" in r_role_closed.json()["detail"]

    # 2. Exclure membre après fermeture -> 400
    r_exc_closed = await client.delete(
        f"/api/v1/teams/{team_id}/members/{m2.id}",
        headers=player_headers,
    )
    assert r_exc_closed.status_code == 400
    assert "fermées" in r_exc_closed.json()["detail"]

    # 3. Transférer capitanat après fermeture -> 400
    r_trans_closed = await client.post(
        f"/api/v1/teams/{team_id}/transfer-captain",
        json={"new_captain_id": str(u2.id)},
        headers=player_headers,
    )
    assert r_trans_closed.status_code == 400
    assert "fermées" in r_trans_closed.json()["detail"]
