import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Team, TeamJoinRequest, TeamMember, Tournament, User
from app.schemas.team import (
    JoinRequestResponse,
    TeamAssignRole,
    TeamCreate,
    TeamMemberResponse,
    TeamResponse,
    TeamTransferCaptain,
    TeamUpdateName,
)


class TeamService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_tournament_or_404(self, tournament_id: uuid.UUID) -> Tournament:
        tournament = await self.db.get(Tournament, tournament_id)
        if not tournament:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tournoi non trouvé",
            )
        return tournament

    async def get_team_with_members_or_404(self, team_id: uuid.UUID) -> Team:
        stmt = (
            select(Team)
            .where(Team.id == team_id)
            .options(
                selectinload(Team.members).selectinload(TeamMember.user),
                selectinload(Team.tournament),
            )
        )
        result = await self.db.execute(stmt)
        team = result.scalar_one_or_none()
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Équipe non trouvée",
            )
        return team

    def _to_team_response(self, team: Team) -> TeamResponse:
        members_resp = [
            TeamMemberResponse(
                id=m.id,
                user_id=m.user_id,
                username=m.user.username if m.user else None,
                game_role=m.game_role,
                joined_at=m.joined_at,
            )
            for m in team.members
        ]
        return TeamResponse(
            id=team.id,
            tournament_id=team.tournament_id,
            name=team.name,
            captain_id=team.captain_id,
            is_eliminated=team.is_eliminated,
            created_at=team.created_at,
            members_count=len(team.members),
            members=members_resp,
        )

    # -------------------------------------------------------------------------
    # Création d'équipe par un joueur (qui devient capitaine)
    # -------------------------------------------------------------------------
    async def create_team(
        self,
        tournament_id: uuid.UUID,
        payload: TeamCreate,
        creator: User,
    ) -> TeamResponse:
        tournament = await self.get_tournament_or_404(tournament_id)

        # Vérification statut tournoi: inscriptions ouvertes
        if tournament.status != "registration_open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Les inscriptions à ce tournoi sont fermées",
            )

        # Un joueur ne peut être que dans une seule équipe par tournoi
        existing_membership = await self.db.execute(
            select(TeamMember).where(
                TeamMember.tournament_id == tournament_id,
                TeamMember.user_id == creator.id,
            )
        )
        if existing_membership.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Vous faites déjà partie d'une équipe pour ce tournoi",
            )

        team = Team(
            tournament_id=tournament_id,
            name=payload.name,
            captain_id=creator.id,
        )
        try:
            self.db.add(team)
            await self.db.flush()  # Récupère l'ID de l'équipe

            # Le capitaine est automatiquement ajouté comme membre de l'équipe
            captain_member = TeamMember(
                team_id=team.id,
                user_id=creator.id,
                tournament_id=tournament_id,
                game_role=payload.game_role,
            )
            self.db.add(captain_member)
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Une équipe avec ce nom existe déjà pour ce tournoi",
            ) from exc

        return await self.get_team(team.id)

    # -------------------------------------------------------------------------
    # Recherche / Consultation des équipes d'un tournoi
    # -------------------------------------------------------------------------
    async def list_teams(
        self,
        tournament_id: uuid.UUID,
        search: str | None = None,
    ) -> list[TeamResponse]:
        await self.get_tournament_or_404(tournament_id)

        stmt = (
            select(Team)
            .where(Team.tournament_id == tournament_id)
            .options(
                selectinload(Team.members).selectinload(TeamMember.user),
            )
            .order_by(Team.created_at.asc())
        )
        if search:
            stmt = stmt.where(Team.name.ilike(f"%{search}%"))

        result = await self.db.execute(stmt)
        teams = result.scalars().all()
        return [self._to_team_response(t) for t in teams]

    async def get_team(self, team_id: uuid.UUID) -> TeamResponse:
        team = await self.get_team_with_members_or_404(team_id)
        return self._to_team_response(team)

    # -------------------------------------------------------------------------
    # Rejoindre une équipe (Max 5 joueurs, inscription ouverte)
    # -------------------------------------------------------------------------
    def _to_join_request_response(self, req: TeamJoinRequest) -> JoinRequestResponse:
        return JoinRequestResponse(
            id=req.id,
            team_id=req.team_id,
            user_id=req.user_id,
            username=req.user.username if req.user else None,
            tournament_id=req.tournament_id,
            game_role=req.game_role,
            status=req.status,
            created_at=req.created_at,
            responded_at=req.responded_at,
        )

    # -------------------------------------------------------------------------
    # Demander à rejoindre une équipe (Requête soumise au capitaine)
    # -------------------------------------------------------------------------
    async def request_to_join_team(
        self,
        team_id: uuid.UUID,
        user: User,
        game_role: str | None = None,
    ) -> JoinRequestResponse:
        team = await self.get_team_with_members_or_404(team_id)

        # Roster ne change plus si registration_closed
        if team.tournament.status != "registration_open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Impossible de demander à rejoindre : les inscriptions sont fermées",
            )

        # Déjà dans une équipe de ce tournoi ?
        existing_membership = await self.db.execute(
            select(TeamMember).where(
                TeamMember.tournament_id == team.tournament_id,
                TeamMember.user_id == user.id,
            )
        )
        if existing_membership.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Vous êtes déjà inscrit dans une équipe pour ce tournoi",
            )

        # Capacité max de 5 joueurs (capitaine inclus)
        if len(team.members) >= 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="L'équipe est déjà complète (maximum 5 joueurs)",
            )

        # Vérifier si une demande en attente existe déjà pour cette équipe
        existing_request = await self.db.execute(
            select(TeamJoinRequest).where(
                TeamJoinRequest.team_id == team.id,
                TeamJoinRequest.user_id == user.id,
                TeamJoinRequest.status == "pending",
            )
        )
        if existing_request.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Vous avez déjà une demande d'adhésion en attente pour cette équipe",
            )

        join_request = TeamJoinRequest(
            team_id=team.id,
            user_id=user.id,
            tournament_id=team.tournament_id,
            game_role=game_role,
            status="pending",
        )
        self.db.add(join_request)
        await self.db.commit()
        await self.db.refresh(join_request)

        # Charger l'utilisateur pour le nom d'affichage
        join_request.user = user
        return self._to_join_request_response(join_request)

    # -------------------------------------------------------------------------
    # Lister les demandes d'adhésion d'une équipe (Capitaine uniquement)
    # -------------------------------------------------------------------------
    async def list_join_requests(
        self,
        team_id: uuid.UUID,
        user: User,
    ) -> list[JoinRequestResponse]:
        team = await self.get_team_with_members_or_404(team_id)

        # Seul le capitaine peut voir les demandes
        if team.captain_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul le capitaine peut consulter les demandes d'adhésion",
            )

        stmt = (
            select(TeamJoinRequest)
            .where(TeamJoinRequest.team_id == team_id)
            .options(selectinload(TeamJoinRequest.user))
            .order_by(TeamJoinRequest.created_at.asc())
        )
        result = await self.db.execute(stmt)
        requests = result.scalars().all()
        return [self._to_join_request_response(r) for r in requests]

    # -------------------------------------------------------------------------
    # Répondre à une demande d'adhésion (Accepter / Refuser) (Capitaine uniquement)
    # -------------------------------------------------------------------------
    async def respond_to_join_request(
        self,
        team_id: uuid.UUID,
        request_id: uuid.UUID,
        action: str,  # "accept" ou "reject"
        user: User,
    ) -> TeamResponse:
        from datetime import UTC, datetime

        team = await self.get_team_with_members_or_404(team_id)

        # Seul le capitaine
        if team.captain_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul le capitaine peut accepter ou refuser les demandes d'adhésion",
            )

        # Roster gelé si inscriptions fermées
        if team.tournament.status != "registration_open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Impossible de modifier les membres : les inscriptions sont fermées",
            )

        join_request = await self.db.get(TeamJoinRequest, request_id)
        if not join_request or join_request.team_id != team_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Demande d'adhésion non trouvée",
            )

        if join_request.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cette demande a déjà été traitée (statut: {join_request.status})",
            )

        if action == "reject":
            join_request.status = "rejected"
            join_request.responded_at = datetime.now(UTC)
            await self.db.commit()
            return await self.get_team(team.id)

        if action == "accept":
            # Capacité max de 5 joueurs
            if len(team.members) >= 5:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="L'équipe est déjà complète (maximum 5 joueurs)",
                )

            # Le joueur a-t-il rejoint une autre équipe entre temps ?
            existing_membership = await self.db.execute(
                select(TeamMember).where(
                    TeamMember.tournament_id == team.tournament_id,
                    TeamMember.user_id == join_request.user_id,
                )
            )
            if existing_membership.scalar_one_or_none():
                join_request.status = "rejected"
                join_request.responded_at = datetime.now(UTC)
                await self.db.commit()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Le joueur est déjà membre d'une autre équipe pour ce tournoi",
                )

            # Ajouter le joueur au roster
            new_member = TeamMember(
                team_id=team.id,
                user_id=join_request.user_id,
                tournament_id=team.tournament_id,
                game_role=join_request.game_role,
            )
            self.db.add(new_member)
            join_request.status = "accepted"
            join_request.responded_at = datetime.now(UTC)

            # Rejeter automatiquement les autres demandes pendantes de ce joueur pour ce tournoi
            other_requests = await self.db.execute(
                select(TeamJoinRequest).where(
                    TeamJoinRequest.tournament_id == team.tournament_id,
                    TeamJoinRequest.user_id == join_request.user_id,
                    TeamJoinRequest.id != join_request.id,
                    TeamJoinRequest.status == "pending",
                )
            )
            for req in other_requests.scalars():
                req.status = "rejected"
                req.responded_at = datetime.now(UTC)

            await self.db.commit()
            await self.db.refresh(team, ["members"])
            return await self.get_team(team.id)

        raise HTTPException(
            status_code=400, detail="Action invalide (accept ou reject attendu)"
        )

    # -------------------------------------------------------------------------
    # Quitter une équipe (tant que les inscriptions sont ouvertes)
    # -------------------------------------------------------------------------
    async def leave_team(
        self,
        team_id: uuid.UUID,
        user: User,
    ) -> dict[str, str]:
        team = await self.get_team_with_members_or_404(team_id)

        # Roster gelé après fermeture
        if team.tournament.status != "registration_open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Impossible de quitter : les inscriptions sont fermées",
            )

        # Vérifier que l'utilisateur est bien membre
        member = next((m for m in team.members if m.user_id == user.id), None)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vous n'êtes pas membre de cette équipe",
            )

        # Si le capitaine quitte : il doit d'abord transférer son capitanat ou dissoudre
        if team.captain_id == user.id:
            # S'il est seul dans l'équipe, on dissout l'équipe
            if len(team.members) == 1:
                await self.db.delete(team)
                await self.db.commit()
                return {"message": "Équipe dissoute avec succès"}
            # S'il y a d'autres membres, il doit transférer le capitanat d'abord
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le capitaine doit transférer son capitanat avant de quitter l'équipe",
            )

        await self.db.delete(member)
        await self.db.commit()
        await self.db.refresh(team, ["members"])
        return {"message": "Vous avez quitté l'équipe avec succès"}

    # -------------------------------------------------------------------------
    # Renommer l'équipe (Capitaine uniquement, inscriptions ouvertes)
    # -------------------------------------------------------------------------
    async def rename_team(
        self,
        team_id: uuid.UUID,
        payload: TeamUpdateName,
        user: User,
    ) -> TeamResponse:
        team = await self.get_team_with_members_or_404(team_id)

        # Seul le capitaine de l'équipe peut modifier
        if team.captain_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul le capitaine peut renommer l'équipe",
            )

        # Roster et équipe gelés
        if team.tournament.status != "registration_open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Impossible de modifier l'équipe : les inscriptions sont fermées",
            )

        team.name = payload.name
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Une équipe avec ce nom existe déjà pour ce tournoi",
            ) from exc

        return await self.get_team(team.id)

    # -------------------------------------------------------------------------
    # Assigner un rôle en jeu (Capitaine uniquement)
    # -------------------------------------------------------------------------
    async def assign_member_role(
        self,
        team_id: uuid.UUID,
        member_id: uuid.UUID,
        payload: TeamAssignRole,
        user: User,
    ) -> TeamResponse:
        team = await self.get_team_with_members_or_404(team_id)

        # Seul le capitaine
        if team.captain_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul le capitaine peut assigner les rôles",
            )

        # Gelé après inscriptions
        if team.tournament.status != "registration_open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Impossible de modifier les rôles : les inscriptions sont fermées",
            )

        member = next(
            (m for m in team.members if m.id == member_id or m.user_id == member_id),
            None,
        )
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membre non trouvé dans cette équipe",
            )

        member.game_role = payload.game_role
        await self.db.commit()
        return await self.get_team(team.id)

    # -------------------------------------------------------------------------
    # Exclure un membre (Capitaine uniquement)
    # -------------------------------------------------------------------------
    async def exclude_member(
        self,
        team_id: uuid.UUID,
        member_id: uuid.UUID,
        user: User,
    ) -> TeamResponse:
        team = await self.get_team_with_members_or_404(team_id)

        # Seul le capitaine
        if team.captain_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul le capitaine peut exclure un membre",
            )

        # Gelé après inscriptions
        if team.tournament.status != "registration_open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Impossible d'exclure un membre : les inscriptions sont fermées",
            )

        member = next(
            (m for m in team.members if m.id == member_id or m.user_id == member_id),
            None,
        )
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membre non trouvé dans cette équipe",
            )

        if member.user_id == team.captain_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le capitaine ne peut pas s'auto-exclure (transférez le capitanat ou quittez l'équipe)",
            )

        await self.db.delete(member)
        await self.db.commit()
        await self.db.refresh(team, ["members"])
        return await self.get_team(team.id)

    # -------------------------------------------------------------------------
    # Transférer le capitanat à un autre membre
    # -------------------------------------------------------------------------
    async def transfer_captaincy(
        self,
        team_id: uuid.UUID,
        payload: TeamTransferCaptain,
        user: User,
    ) -> TeamResponse:
        team = await self.get_team_with_members_or_404(team_id)

        # Seul le capitaine actuel
        if team.captain_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seul le capitaine actuel peut transférer son rôle",
            )

        # Gelé après inscriptions
        if team.tournament.status != "registration_open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Impossible de transférer le capitanat : les inscriptions sont fermées",
            )

        new_captain_member = next(
            (
                m
                for m in team.members
                if m.user_id == payload.new_captain_id or m.id == payload.new_captain_id
            ),
            None,
        )
        if not new_captain_member:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le nouveau capitaine doit déjà être membre de l'équipe",
            )

        team.captain_id = new_captain_member.user_id
        await self.db.commit()
        return await self.get_team(team.id)
