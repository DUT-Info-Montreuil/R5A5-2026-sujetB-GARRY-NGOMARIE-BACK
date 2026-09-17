"""Espaces d'echange d'equipe (B-16, B-17, B-18).

Toutes les regles d'acces vivent ici (couche service, deny-by-default). Chaque
appel re-verifie l'appartenance depuis la base : aucune autorisation mise en
cache, donc un joueur exclu (B-17) ou une equipe eliminee (B-18) sont pris en
compte des la requete suivante, y compris sur un socket deja ouvert.
"""

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.entities import Message, Team, TeamMember, User
from app.realtime.manager import manager, team_room
from app.schemas.chat import MessageResponse

logger = logging.getLogger("app.chat")


class ChatService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_team_or_404(self, team_id: uuid.UUID) -> Team:
        team = await self.db.get(Team, team_id)
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Équipe non trouvée",
            )
        return team

    async def _is_member(self, team_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            select(TeamMember.id).where(
                TeamMember.team_id == team_id,
                TeamMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None

    # -------------------------------------------------------------------------
    # Gardes d'acces
    # -------------------------------------------------------------------------
    async def ensure_can_read(self, team_id: uuid.UUID, user: User) -> Team:
        """Lecture : membre courant de l'equipe, ou admin.

        B-18 : une equipe eliminee a son espace ferme ; seul l'admin y lit encore.
        """
        team = await self._get_team_or_404(team_id)

        if user.global_role == "admin":
            return team

        if team.is_eliminated:
            logger.info(
                "chat read denied team=%s user=%s reason=eliminated", team_id, user.id
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="L'espace de cette équipe est fermé (équipe éliminée)",
            )

        if not await self._is_member(team_id, user.id):
            logger.info(
                "chat read denied team=%s user=%s reason=not_member", team_id, user.id
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès réservé aux membres de l'équipe",
            )
        return team

    async def ensure_can_post(self, team_id: uuid.UUID, user: User) -> Team:
        """Ecriture : membre courant, equipe non eliminee (B-16, B-18).

        L'admin peut lire mais pas ecrire dans un espace d'equipe.
        """
        team = await self._get_team_or_404(team_id)

        if not await self._is_member(team_id, user.id):
            logger.info(
                "chat post denied team=%s user=%s reason=not_member", team_id, user.id
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seuls les membres de l'équipe peuvent écrire",
            )

        if team.is_eliminated:
            logger.info(
                "chat post denied team=%s user=%s reason=eliminated", team_id, user.id
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="L'espace de cette équipe est fermé (équipe éliminée)",
            )
        return team

    # -------------------------------------------------------------------------
    # Operations
    # -------------------------------------------------------------------------
    async def list_messages(
        self, team_id: uuid.UUID, user: User
    ) -> list[MessageResponse]:
        await self.ensure_can_read(team_id, user)
        stmt = (
            select(Message)
            .where(Message.team_id == team_id)
            .options(selectinload(Message.author))
            .order_by(Message.created_at.asc())
            .limit(settings.chat_history_limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [self._to_response(m) for m in rows]

    async def post_message(
        self, team_id: uuid.UUID, user: User, content: str
    ) -> MessageResponse:
        await self.ensure_can_post(team_id, user)

        content = content.strip()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Message vide",
            )
        if len(content) > settings.chat_message_max_length:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Message trop long "
                    f"(max {settings.chat_message_max_length} caractères)"
                ),
            )

        message = Message(team_id=team_id, author_id=user.id, content=content)
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        message.author = user

        payload = self._to_response(message)
        logger.info(
            "chat post ok team=%s user=%s message=%s", team_id, user.id, message.id
        )
        await manager.broadcast(
            team_room(team_id),
            {"type": "message", "data": payload.model_dump(mode="json")},
        )
        return payload

    @staticmethod
    def _to_response(message: Message) -> MessageResponse:
        return MessageResponse(
            id=message.id,
            team_id=message.team_id,
            author_id=message.author_id,
            author_username=message.author.username if message.author else None,
            content=message.content,
            created_at=message.created_at,
        )
