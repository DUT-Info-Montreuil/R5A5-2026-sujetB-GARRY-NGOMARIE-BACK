import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.dependencies import CurrentUser, DbSession
from app.schemas.team import (
    JoinRequestCreate,
    JoinRequestResponse,
    TeamAssignRole,
    TeamCreate,
    TeamResponse,
    TeamTransferCaptain,
    TeamUpdateName,
)
from app.services.team_service import TeamService

# Router pour les équipes liées à un tournoi (/api/v1/tournaments/{tournament_id}/teams)
tournament_teams_router = APIRouter(
    prefix="/tournaments/{tournament_id}/teams",
    tags=["teams"],
)

# Router pour les actions directes sur une équipe (/api/v1/teams/{team_id})
teams_router = APIRouter(
    prefix="/teams",
    tags=["teams"],
)


# =============================================================================
# Créer une équipe dans un tournoi
# =============================================================================
@tournament_teams_router.post(
    "",
    response_model=TeamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une équipe pour un tournoi",
)
async def create_team(
    tournament_id: uuid.UUID,
    payload: TeamCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> TeamResponse:
    service = TeamService(db)
    return await service.create_team(tournament_id, payload, current_user)


# =============================================================================
# Rechercher / Lister les équipes d'un tournoi (public)
# =============================================================================
@tournament_teams_router.get(
    "",
    response_model=list[TeamResponse],
    summary="Lister ou rechercher des équipes dans un tournoi",
)
async def list_teams(
    tournament_id: uuid.UUID,
    db: DbSession,
    search: Annotated[str | None, Query(description="Filtrer par nom d'équipe")] = None,
) -> list[TeamResponse]:
    service = TeamService(db)
    return await service.list_teams(tournament_id, search=search)


# =============================================================================
# Obtenir le détail d'une équipe
# =============================================================================
@teams_router.get(
    "/{team_id}",
    response_model=TeamResponse,
    summary="Consulter les détails et membres d'une équipe",
)
async def get_team(
    team_id: uuid.UUID,
    db: DbSession,
) -> TeamResponse:
    service = TeamService(db)
    return await service.get_team(team_id)


# =============================================================================
# Demander à rejoindre une équipe (Requête d'adhésion)
# =============================================================================
@teams_router.post(
    "/{team_id}/join",
    response_model=JoinRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Demander à rejoindre une équipe (Soumis à validation du capitaine)",
)
async def request_to_join_team(
    team_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    payload: JoinRequestCreate | None = None,
) -> JoinRequestResponse:
    service = TeamService(db)
    game_role = payload.game_role if payload else None
    return await service.request_to_join_team(
        team_id, current_user, game_role=game_role
    )


# =============================================================================
# Consulter les demandes d'adhésion (Capitaine uniquement)
# =============================================================================
@teams_router.get(
    "/{team_id}/join-requests",
    response_model=list[JoinRequestResponse],
    summary="Consulter les demandes d'adhésion en attente (Capitaine uniquement)",
)
async def list_join_requests(
    team_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> list[JoinRequestResponse]:
    service = TeamService(db)
    return await service.list_join_requests(team_id, current_user)


# =============================================================================
# Répondre à une demande (Accepter / Refuser) (Capitaine uniquement)
# =============================================================================
@teams_router.post(
    "/{team_id}/join-requests/{request_id}/{action}",
    response_model=TeamResponse,
    summary="Accepter ou refuser une demande d'adhésion (Capitaine uniquement)",
)
async def respond_to_join_request(
    team_id: uuid.UUID,
    request_id: uuid.UUID,
    action: str,  # "accept" ou "reject"
    current_user: CurrentUser,
    db: DbSession,
) -> TeamResponse:
    service = TeamService(db)
    return await service.respond_to_join_request(
        team_id, request_id, action, current_user
    )


# =============================================================================
# Quitter une équipe
# =============================================================================
@teams_router.post(
    "/{team_id}/leave",
    summary="Quitter une équipe",
)
async def leave_team(
    team_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
):
    service = TeamService(db)
    return await service.leave_team(team_id, current_user)


# =============================================================================
# Renommer l'équipe (Capitaine uniquement)
# =============================================================================
@teams_router.patch(
    "/{team_id}/name",
    response_model=TeamResponse,
    summary="Renommer l'équipe (Capitaine uniquement)",
)
async def rename_team(
    team_id: uuid.UUID,
    payload: TeamUpdateName,
    current_user: CurrentUser,
    db: DbSession,
) -> TeamResponse:
    service = TeamService(db)
    return await service.rename_team(team_id, payload, current_user)


# =============================================================================
# Assigner un rôle à un membre (Capitaine uniquement)
# =============================================================================
@teams_router.patch(
    "/{team_id}/members/{member_id}/role",
    response_model=TeamResponse,
    summary="Assigner un rôle à un joueur (Capitaine uniquement)",
)
async def assign_role(
    team_id: uuid.UUID,
    member_id: uuid.UUID,
    payload: TeamAssignRole,
    current_user: CurrentUser,
    db: DbSession,
) -> TeamResponse:
    service = TeamService(db)
    return await service.assign_member_role(team_id, member_id, payload, current_user)


# =============================================================================
# Exclure un membre (Capitaine uniquement)
# =============================================================================
@teams_router.delete(
    "/{team_id}/members/{member_id}",
    response_model=TeamResponse,
    summary="Exclure un membre de l'équipe (Capitaine uniquement)",
)
async def exclude_member(
    team_id: uuid.UUID,
    member_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> TeamResponse:
    service = TeamService(db)
    return await service.exclude_member(team_id, member_id, current_user)


# =============================================================================
# Transférer le capitanat (Capitaine uniquement)
# =============================================================================
@teams_router.post(
    "/{team_id}/transfer-captain",
    response_model=TeamResponse,
    summary="Transférer le capitanat à un autre joueur (Capitaine uniquement)",
)
async def transfer_captaincy(
    team_id: uuid.UUID,
    payload: TeamTransferCaptain,
    current_user: CurrentUser,
    db: DbSession,
) -> TeamResponse:
    service = TeamService(db)
    return await service.transfer_captaincy(team_id, payload, current_user)
