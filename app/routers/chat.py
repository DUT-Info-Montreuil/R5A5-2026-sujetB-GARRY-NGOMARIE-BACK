"""Espace d'echange d'equipe : REST + WebSocket (B-16, B-17, B-18).

- `GET  /api/v1/teams/{team_id}/messages` : historique (repli si un client a
  rate des messages temps reel).
- `POST /api/v1/teams/{team_id}/messages` : publier (aussi diffuse en temps reel).
- `WS   /api/v1/teams/{team_id}/ws` : flux bidirectionnel. Authentifie par le
  cookie de session (le navigateur l'envoie a l'ouverture) ; l'en-tete Origin
  doit etre autorise, sinon la poignee de main est refusee (CSWSH).

Toutes les regles d'acces sont dans `ChatService` et re-verifiees en base a
chaque message : aucune autorisation mise en cache (B-17).
"""

import logging
import uuid

from fastapi import (
    APIRouter,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import CurrentUser, DbSession
from app.models.entities import User
from app.realtime.manager import (
    WS_CLOSE_FORBIDDEN,
    WS_CLOSE_NOT_FOUND,
    WS_CLOSE_UNAUTHENTICATED,
    manager,
    team_room,
)
from app.schemas.chat import MessageCreate, MessageResponse
from app.services.auth_service import user_for_session
from app.services.chat_service import ChatService

router = APIRouter(prefix="/teams/{team_id}", tags=["chat"])
logger = logging.getLogger("app.chat")


@router.get(
    "/messages",
    response_model=list[MessageResponse],
    summary="Historique de l'espace d'echange (membre de l'equipe ou admin)",
)
async def get_messages(
    team_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
) -> list[MessageResponse]:
    return await ChatService(db).list_messages(team_id, current_user)


@router.post(
    "/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Publier un message (membre de l'equipe, equipe non eliminee)",
)
async def post_message(
    team_id: uuid.UUID,
    payload: MessageCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> MessageResponse:
    return await ChatService(db).post_message(team_id, current_user, payload.content)


async def _resolve_ws_user(websocket: WebSocket, db: AsyncSession) -> User | None:
    """Meme session que le REST ; None si cookie absent, invalide ou expire."""
    token = websocket.cookies.get(settings.session_cookie_name)
    return await user_for_session(db, token) if token else None


async def _handle_frame(
    frame: object,
    team_id: uuid.UUID,
    user: User,
    websocket: WebSocket,
    db: AsyncSession,
) -> None:
    """Une trame client. Seul `{"type": "message", "content": "..."}` est accepte."""
    if not isinstance(frame, dict) or frame.get("type") != "message":
        await websocket.send_json({"type": "error", "detail": "Trame non reconnue"})
        return
    content = frame.get("content")
    if not isinstance(content, str):
        await websocket.send_json(
            {"type": "error", "detail": "Champ 'content' (texte) requis"}
        )
        return
    try:
        # Re-verification d'acces en base a chaque message (B-17).
        await ChatService(db).post_message(team_id, user, content)
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "detail": exc.detail})
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            await websocket.close(code=WS_CLOSE_FORBIDDEN)
            raise WebSocketDisconnect(code=WS_CLOSE_FORBIDDEN) from exc


@router.websocket("/ws")
async def team_chat_ws(
    websocket: WebSocket,
    team_id: uuid.UUID,
    db: DbSession,
) -> None:
    # Un navigateur ne peut pas forger Origin : refuse avant tout echange.
    if websocket.headers.get("origin") not in settings.allowed_origins:
        logger.info("ws auth denied team=%s reason=bad_origin", team_id)
        await websocket.close(code=WS_CLOSE_FORBIDDEN)
        return

    await websocket.accept()

    user = await _resolve_ws_user(websocket, db)
    if user is None:
        logger.info("ws auth denied team=%s reason=no_session", team_id)
        await websocket.send_json(
            {"type": "error", "detail": "Session manquante ou invalide"}
        )
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
        return

    service = ChatService(db)
    try:
        await service.ensure_can_read(team_id, user)
    except HTTPException as exc:
        code = (
            WS_CLOSE_NOT_FOUND
            if exc.status_code == status.HTTP_404_NOT_FOUND
            else WS_CLOSE_FORBIDDEN
        )
        logger.info("ws auth denied team=%s user=%s code=%d", team_id, user.id, code)
        await websocket.send_json({"type": "error", "detail": exc.detail})
        await websocket.close(code=code)
        return

    room = team_room(team_id)
    await manager.connect(room, user.id, websocket)
    await websocket.send_json({"type": "system", "event": "connected", "room": room})
    try:
        while True:
            frame = await websocket.receive_json()
            await _handle_frame(frame, team_id, user, websocket, db)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(room, user.id, websocket)
