import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Tournament
from app.schemas.tournament import TournamentCreate


class TournamentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_tournament(
        self,
        payload: TournamentCreate,
        creator_id: uuid.UUID,
    ) -> Tournament:
        """
        L'administrateur crée un tournoi en indiquant le jeu et ouvre les inscriptions.
        Le statut initial est systématiquement 'registration_open'.
        """
        tournament = Tournament(
            name=payload.name,
            game=payload.game,
            status="registration_open",
            created_by=creator_id,
        )
        self.db.add(tournament)
        await self.db.commit()
        await self.db.refresh(tournament)
        return tournament

    async def get_by_id(self, tournament_id: uuid.UUID) -> Tournament | None:
        return await self.db.get(Tournament, tournament_id)

    async def list_tournaments(self) -> list[Tournament]:
        stmt = select(Tournament).order_by(Tournament.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
