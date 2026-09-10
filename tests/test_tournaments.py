import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_admin_can_create_tournament(
    client: AsyncClient,
    admin_headers: dict[str, str],
    admin_user,
):
    """
    L'administrateur crée un tournoi en indiquant le jeu et ouvre les inscriptions.
    Doit retourner 201 Created avec status 'registration_open'.
    """
    payload = {
        "name": "IUT Inter-Regional Championship",
        "game": "Rocket League",
    }
    response = await client.post(
        "/api/v1/tournaments",
        json=payload,
        headers=admin_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == payload["name"]
    assert data["game"] == payload["game"]
    assert data["status"] == "registration_open"
    assert data["created_by"] == str(admin_user.id)
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_player_cannot_create_tournament(
    client: AsyncClient,
    player_headers: dict[str, str],
):
    """
    Contrôle d'accès (négatif): Un joueur avec global_role 'player'
    ne peut PAS créer de tournoi -> 403 Forbidden.
    """
    payload = {
        "name": "Unauthorized Tournament",
        "game": "Counter-Strike 2",
    }
    response = await client.post(
        "/api/v1/tournaments",
        json=payload,
        headers=player_headers,
    )
    assert response.status_code == 403
    assert "Accès interdit" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unauthenticated_cannot_create_tournament(client: AsyncClient):
    """
    Contrôle d'accès (négatif): Un visiteur non authentifié
    ne peut PAS créer de tournoi -> 401 Unauthorized.
    """
    payload = {
        "name": "Anonymous Tournament",
        "game": "Valorant",
    }
    response = await client.post(
        "/api/v1/tournaments",
        json=payload,
    )
    assert response.status_code == 401
    assert "Non authentifié" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_tournament_validation_errors(
    client: AsyncClient,
    admin_headers: dict[str, str],
):
    """
    Validation API: Vérification du nom et jeu requis.
    """
    # Nom vide
    response = await client.post(
        "/api/v1/tournaments",
        json={"name": "A", "game": "LoL"},
        headers=admin_headers,
    )
    assert response.status_code == 422

    # Champ manquant
    response = await client.post(
        "/api/v1/tournaments",
        json={"name": "Valid Name"},
        headers=admin_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_tournaments_public(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session,
):
    """
    N'importe qui (même non authentifié) peut lister les tournois.
    """
    # Créer un tournoi
    await client.post(
        "/api/v1/tournaments",
        json={"name": "Public Cup", "game": "Apex Legends"},
        headers=admin_headers,
    )

    # Récupérer sans headers d'authentification
    response = await client.get("/api/v1/tournaments")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(t["name"] == "Public Cup" for t in data)

    # Tester TournamentService.get_by_id
    import uuid

    from app.services.tournament_service import TournamentService

    service = TournamentService(db_session)
    tourn_id = uuid.UUID(data[0]["id"])
    found = await service.get_by_id(tourn_id)
    assert found is not None
    assert found.id == tourn_id

    not_found = await service.get_by_id(uuid.uuid4())
    assert not_found is None
