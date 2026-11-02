"""Cycle de vie du tournoi et competition (B-03, B-04, B-12 a B-15).

Les gardes d'etat (tournoi en cours, match jouable, equipe du match) sont
relues en base ici ; le routeur verifie seulement que l'appelant est admin.
Le tableau est une elimination directe dimensionnee a la puissance de deux
superieure ou egale au nombre d'equipes engagees (context.md, section 7).

Etats d'un match : `pending` tant qu'une equipe manque ou que le tournoi n'est
pas lance, `in_progress` quand il est jouable, puis `completed` ou `forfeit`.
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Match, Team, TeamMember, Tournament
from app.realtime.manager import manager, team_room, tournament_room
from app.schemas.match import MatchResponse, MatchTeam

logger = logging.getLogger("app.competition")

FULL_ROSTER = 5


def _bracket_size(team_count: int) -> int:
    size = 2
    while size < team_count:
        size *= 2
    return size


class CompetitionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        # Effets de bord a executer une fois la transaction validee.
        self._eliminated: list[Team] = []
        self._events: list[dict] = []

    # ------------------------------------------------------------------ lecture

    async def _tournament_or_404(self, tournament_id: uuid.UUID) -> Tournament:
        tournament = await self.db.get(Tournament, tournament_id)
        if tournament is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Tournoi non trouvé")
        return tournament

    async def tournament_exists(self, tournament_id: uuid.UUID) -> bool:
        return await self.db.get(Tournament, tournament_id) is not None

    async def _matches(self, tournament_id: uuid.UUID) -> list[Match]:
        result = await self.db.execute(
            select(Match)
            .where(Match.tournament_id == tournament_id)
            .order_by(Match.round, Match.match_number)
        )
        return list(result.scalars().all())

    async def _to_responses(self, matches: list[Match]) -> list[MatchResponse]:
        ids = {t for m in matches for t in (m.team1_id, m.team2_id) if t}
        teams: dict[uuid.UUID, MatchTeam] = {}
        if ids:
            result = await self.db.execute(select(Team).where(Team.id.in_(ids)))
            teams = {t.id: MatchTeam(id=t.id, name=t.name) for t in result.scalars()}
        return [
            MatchResponse(
                id=m.id,
                tournament_id=m.tournament_id,
                round=m.round,
                match_number=m.match_number,
                team1_id=m.team1_id,
                team2_id=m.team2_id,
                team1=teams.get(m.team1_id),
                team2=teams.get(m.team2_id),
                winner_id=m.winner_id,
                team1_score=m.team1_score,
                team2_score=m.team2_score,
                status=m.status,
                next_match_id=m.next_match_id,
                next_match_slot=m.next_match_slot,
            )
            for m in matches
        ]

    async def list_matches(self, tournament_id: uuid.UUID) -> list[MatchResponse]:
        await self._tournament_or_404(tournament_id)
        return await self._to_responses(await self._matches(tournament_id))

    async def _roster_size(self, team_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(TeamMember)
            .where(TeamMember.team_id == team_id)
        )
        return result.scalar_one()

    # ------------------------------------------------------- B-03 / B-12 : close

    async def close_registration(self, tournament_id: uuid.UUID) -> Tournament:
        tournament = await self._tournament_or_404(tournament_id)
        if tournament.status != "registration_open":
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Les inscriptions ne sont pas ouvertes"
            )
        result = await self.db.execute(
            select(Team)
            .where(Team.tournament_id == tournament_id)
            .order_by(Team.created_at, Team.id)
        )
        teams = list(result.scalars().all())
        if len(teams) < 2:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Au moins 2 équipes engagées sont nécessaires pour former un tableau",
            )

        await self._build_bracket(tournament, teams)
        tournament.status = "registration_closed"
        tournament.registration_closed_at = datetime.now(UTC)
        logger.info(
            "state transition tournament=%s registration_open->registration_closed teams=%d",
            tournament_id,
            len(teams),
        )
        self._events.append(self._status_event(tournament))
        return await self._commit_tournament(tournament)

    async def _build_bracket(self, tournament: Tournament, teams: list[Team]) -> None:
        """Cree tous les matchs ; les byes vont aux premieres equipes inscrites."""
        size = _bracket_size(len(teams))
        byes = size - len(teams)
        rounds = size.bit_length() - 1

        by_round: dict[int, list[Match]] = {}
        for rnd in range(1, rounds + 1):
            by_round[rnd] = [
                Match(tournament_id=tournament.id, round=rnd, match_number=n)
                for n in range(1, size // 2**rnd + 1)
            ]
            self.db.add_all(by_round[rnd])
        await self.db.flush()

        for rnd in range(1, rounds):
            for match in by_round[rnd]:
                match.next_match_id = by_round[rnd + 1][
                    (match.match_number - 1) // 2
                ].id
                match.next_match_slot = 1 if match.match_number % 2 else 2

        queue = list(teams)
        for index, match in enumerate(by_round[1]):
            match.team1_id = queue.pop(0).id
            if index < byes:
                # Bye : qualifiee d'office pour le tour suivant.
                match.status = "completed"
                match.winner_id = match.team1_id
                nxt = by_round[2][index // 2]
                setattr(nxt, f"team{match.next_match_slot}_id", match.winner_id)
            else:
                match.team2_id = queue.pop(0).id

    # ------------------------------------------------------------ B-04 : start

    async def start_tournament(self, tournament_id: uuid.UUID) -> Tournament:
        tournament = await self._tournament_or_404(tournament_id)
        if tournament.status != "registration_closed":
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Les inscriptions ne sont pas closes"
            )
        tournament.status = "running"
        self._events.append(self._status_event(tournament))
        logger.info(
            "state transition tournament=%s registration_closed->running",
            tournament_id,
        )
        # Les matchs deja composes deviennent jouables ; une equipe incomplete
        # perd son premier match par forfait.
        for match in await self._matches(tournament_id):
            if match.status == "pending" and match.team1_id and match.team2_id:
                await self._activate(tournament, match)
        await self._finish_if_done(tournament)
        return await self._commit_tournament(tournament)

    # ------------------------------------------------- B-13 / B-14 / B-15 : play

    async def _playable_match(
        self, tournament_id: uuid.UUID, match_id: uuid.UUID
    ) -> tuple[Tournament, Match]:
        tournament = await self._tournament_or_404(tournament_id)
        match = await self.db.get(Match, match_id)
        if match is None or match.tournament_id != tournament_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Match non trouvé")
        if tournament.status != "running":
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Le tournoi n'est pas en cours"
            )
        if match.status != "in_progress":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Le match n'est pas jouable (équipes inconnues ou déjà terminé)",
            )
        return tournament, match

    async def enter_result(
        self,
        tournament_id: uuid.UUID,
        match_id: uuid.UUID,
        team1_score: int,
        team2_score: int,
    ) -> MatchResponse:
        tournament, match = await self._playable_match(tournament_id, match_id)
        if team1_score == team2_score:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Égalité impossible : un match d'élimination directe a un vainqueur",
            )
        match.team1_score = team1_score
        match.team2_score = team2_score
        winner = match.team1_id if team1_score > team2_score else match.team2_id
        logger.info(
            "result entered tournament=%s match=%s score=%d-%d",
            tournament_id,
            match_id,
            team1_score,
            team2_score,
        )
        await self._settle(tournament, match, winner, "completed")
        await self._finish_if_done(tournament)
        await self._commit_tournament(tournament)
        return (await self._to_responses([match]))[0]

    async def declare_forfeit(
        self,
        tournament_id: uuid.UUID,
        match_id: uuid.UUID,
        forfeiting_team_id: uuid.UUID,
    ) -> MatchResponse:
        tournament, match = await self._playable_match(tournament_id, match_id)
        if forfeiting_team_id not in (match.team1_id, match.team2_id):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Cette équipe ne joue pas ce match"
            )
        winner = (
            match.team2_id if forfeiting_team_id == match.team1_id else match.team1_id
        )
        logger.info(
            "forfeit declared tournament=%s match=%s team=%s",
            tournament_id,
            match_id,
            forfeiting_team_id,
        )
        await self._settle(tournament, match, winner, "forfeit")
        await self._finish_if_done(tournament)
        await self._commit_tournament(tournament)
        return (await self._to_responses([match]))[0]

    async def _settle(
        self,
        tournament: Tournament,
        match: Match,
        winner_id: uuid.UUID,
        match_status: str,
    ) -> None:
        """Enregistre le vainqueur, elimine le perdant, fait avancer le tableau."""
        match.status = match_status
        match.winner_id = winner_id
        loser_id = match.team2_id if winner_id == match.team1_id else match.team1_id
        loser = await self.db.get(Team, loser_id)
        loser.is_eliminated = True
        self._eliminated.append(loser)

        if match.next_match_id is not None:
            nxt = await self.db.get(Match, match.next_match_id)
            setattr(nxt, f"team{match.next_match_slot}_id", winner_id)
            if nxt.team1_id and nxt.team2_id:
                await self._activate(tournament, nxt)

        (response,) = await self._to_responses([match])
        self._events.append(
            {
                "type": "tournament",
                "event": "match_updated",
                "data": response.model_dump(mode="json"),
            }
        )

    async def _activate(self, tournament: Tournament, match: Match) -> None:
        """Rend un match jouable, sauf forfait automatique d'une equipe incomplete."""
        match.status = "in_progress"
        size_a = size_b = FULL_ROSTER
        if await self._is_first_match(match.team1_id, match.id):
            size_a = await self._roster_size(match.team1_id)
        if await self._is_first_match(match.team2_id, match.id):
            size_b = await self._roster_size(match.team2_id)
        if size_a >= FULL_ROSTER and size_b >= FULL_ROSTER:
            return
        if size_a == size_b:
            # Deux equipes incompletes a egalite : l'admin tranche.
            return
        winner = match.team1_id if size_a > size_b else match.team2_id
        logger.info(
            "auto forfeit tournament=%s match=%s roster_sizes=%d/%d",
            tournament.id,
            match.id,
            size_a,
            size_b,
        )
        await self._settle(tournament, match, winner, "forfeit")

    async def _is_first_match(self, team_id: uuid.UUID, current_id: uuid.UUID) -> bool:
        """Vrai si l'equipe n'a encore joue aucun vrai match (un bye ne compte pas)."""
        result = await self.db.execute(
            select(func.count())
            .select_from(Match)
            .where(
                Match.id != current_id,
                Match.status.in_(("completed", "forfeit")),
                Match.team1_id.is_not(None),
                Match.team2_id.is_not(None),
                (Match.team1_id == team_id) | (Match.team2_id == team_id),
            )
        )
        return result.scalar_one() == 0

    async def _finish_if_done(self, tournament: Tournament) -> None:
        result = await self.db.execute(
            select(Match)
            .where(Match.tournament_id == tournament.id, Match.next_match_id.is_(None))
            .order_by(Match.round.desc())
        )
        final = result.scalars().first()
        if (
            tournament.status == "running"
            and final is not None
            and final.status in ("completed", "forfeit")
        ):
            tournament.status = "finished"
            logger.info(
                "state transition tournament=%s running->finished", tournament.id
            )
            self._events.append(self._status_event(tournament))

    # ------------------------------------------------------------- temps reel

    @staticmethod
    def _status_event(tournament: Tournament) -> dict:
        return {
            "type": "tournament",
            "event": "status_changed",
            "data": {"tournament_id": str(tournament.id), "status": tournament.status},
        }

    async def _commit_tournament(self, tournament: Tournament) -> Tournament:
        """Valide, puis notifie : la base fait foi, la diffusion n'est qu'un signal."""
        await self.db.commit()
        for team in self._eliminated:
            await self._close_team_room(team)
        for event in self._events:
            await manager.broadcast(tournament_room(tournament.id), event)
        await self.db.refresh(tournament)
        return tournament

    async def _close_team_room(self, team: Team) -> None:
        """B-18 : l'equipe eliminee perd son espace d'echange en direct."""
        result = await self.db.execute(
            select(TeamMember.user_id).where(TeamMember.team_id == team.id)
        )
        for user_id in result.scalars().all():
            await manager.revoke(team_room(team.id), user_id, reason="eliminated")
