from fastapi import APIRouter, status

from app.core.dependencies import AdminUser, DbSession
from app.schemas.tournament import TournamentCreate, TournamentResponse
from app.services.tournament_service import TournamentService

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


@router.post(
    "",
    response_model=TournamentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un tournoi et ouvrir les inscriptions (Admin uniquement)",
    description="L'administrateur crée un tournoi en indiquant le jeu et ouvre les inscriptions. Accessible uniquement par un administrateur.",
)
async def create_tournament(
    payload: TournamentCreate,
    current_admin: AdminUser,
    db: DbSession,
) -> TournamentResponse:
    service = TournamentService(db)
    return await service.create_tournament(payload, creator_id=current_admin.id)


@router.get(
    "",
    response_model=list[TournamentResponse],
    summary="Lister les tournois (Public)",
)
async def list_tournaments(db: DbSession) -> list[TournamentResponse]:
    service = TournamentService(db)
    return await service.list_tournaments()
