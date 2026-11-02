"""Cycle de vie du tournoi et competition (B-03, B-04, B-12 a B-15).

Les transitions et la saisie des resultats sont reservees a l'admin ; la
consultation du tableau est publique (B-02). Flux temps reel public :
`WS /api/v1/tournaments/{id}/ws` (B-19).
"""

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.dependencies import AdminUser, DbSession
from app.realtime.manager import (
    WS_CLOSE_FORBIDDEN,
    WS_CLOSE_NOT_FOUND,
    manager,
    tournament_room,
)
from app.schemas.match import MatchForfeit, MatchResponse, MatchResult
from app.schemas.tournament import TournamentResponse
from app.services.competition_service import CompetitionService

router = APIRouter(prefix="/tournaments/{tournament_id}", tags=["competition"])


@router.post(
    "/close-registration",
    response_model=TournamentResponse,
    summary="Clôturer les inscriptions et générer le tableau (Admin uniquement)",
    description="Gèle les équipes et construit le tableau à élimination directe. Refusé s'il y a moins de 2 équipes engagées.",
)
async def close_registration(
    tournament_id: uuid.UUID, _admin: AdminUser, db: DbSession
) -> TournamentResponse:
    return await CompetitionService(db).close_registration(tournament_id)


@router.post(
    "/start",
    response_model=TournamentResponse,
    summary="Démarrer le tournoi (Admin uniquement)",
    description="Passe le tournoi en cours. Les équipes incomplètes perdent leur premier match par forfait.",
)
async def start_tournament(
    tournament_id: uuid.UUID, _admin: AdminUser, db: DbSession
) -> TournamentResponse:
    return await CompetitionService(db).start_tournament(tournament_id)


@router.get(
    "/matches",
    response_model=list[MatchResponse],
    summary="Tableau et progression du tournoi (Public)",
)
async def list_matches(tournament_id: uuid.UUID, db: DbSession) -> list[MatchResponse]:
    return await CompetitionService(db).list_matches(tournament_id)


@router.post(
    "/matches/{match_id}/result",
    response_model=MatchResponse,
    summary="Saisir le résultat d'un match (Admin uniquement)",
    description="Le vainqueur avance au match suivant. Refusé hors tournoi en cours, si une équipe est inconnue, si le match est déjà validé ou en cas d'égalité.",
)
async def enter_result(
    tournament_id: uuid.UUID,
    match_id: uuid.UUID,
    payload: MatchResult,
    _admin: AdminUser,
    db: DbSession,
) -> MatchResponse:
    return await CompetitionService(db).enter_result(
        tournament_id, match_id, payload.team1_score, payload.team2_score
    )


@router.post(
    "/matches/{match_id}/forfeit",
    response_model=MatchResponse,
    summary="Déclarer le forfait d'une équipe (Admin uniquement)",
    description="L'adversaire est qualifié et l'équipe forfait est éliminée.",
)
async def declare_forfeit(
    tournament_id: uuid.UUID,
    match_id: uuid.UUID,
    payload: MatchForfeit,
    _admin: AdminUser,
    db: DbSession,
) -> MatchResponse:
    return await CompetitionService(db).declare_forfeit(
        tournament_id, match_id, payload.forfeiting_team_id
    )


@router.websocket("/ws")
async def tournament_ws(
    websocket: WebSocket, tournament_id: uuid.UUID, db: DbSession
) -> None:
    """Suivi public en lecture seule : aucune session requise, aucune trame acceptee."""
    if websocket.headers.get("origin") not in settings.allowed_origins:
        await websocket.close(code=WS_CLOSE_FORBIDDEN)
        return
    await websocket.accept()
    if not await CompetitionService(db).tournament_exists(tournament_id):
        await websocket.close(code=WS_CLOSE_NOT_FOUND)
        return
    room = tournament_room(tournament_id)
    # Les spectateurs sont anonymes : une cle unique par socket.
    spectator = uuid.uuid4()
    await manager.connect(room, spectator, websocket)
    await websocket.send_json({"type": "system", "event": "connected", "room": room})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(room, spectator, websocket)
