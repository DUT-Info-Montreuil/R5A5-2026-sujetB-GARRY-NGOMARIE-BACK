"""Gestionnaire unique de connexions WebSocket (X-05).

Une seule instance (`manager`) partagee par tout le process. Les connexions sont
rangees par salle : `team:<id>` pour les espaces d'echange d'equipe (B-16) et
`tournament:<id>`, reserve au suivi public temps reel (B-19, pas encore de
producteur). Un meme utilisateur peut avoir plusieurs sockets (onglets).

La diffusion est une notification : l'ecriture en base fait foi, le socket ne
sert qu'a pousser. Un client qui a rate un message le retrouve via REST.
"""

import logging
import uuid

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

logger = logging.getLogger("app.realtime")

# Codes de fermeture applicatifs (plage 4000-4999 reservee aux applications).
WS_CLOSE_UNAUTHENTICATED = 4401
WS_CLOSE_FORBIDDEN = 4403
WS_CLOSE_NOT_FOUND = 4404


def team_room(team_id: uuid.UUID) -> str:
    return f"team:{team_id}"


def tournament_room(tournament_id: uuid.UUID) -> str:
    return f"tournament:{tournament_id}"


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, dict[uuid.UUID, set[WebSocket]]] = {}

    async def connect(
        self, room: str, user_id: uuid.UUID, websocket: WebSocket
    ) -> None:
        """Enregistre un socket deja accepte dans une salle."""
        self._rooms.setdefault(room, {}).setdefault(user_id, set()).add(websocket)
        logger.info(
            "ws connect room=%s user=%s sockets=%d",
            room,
            user_id,
            len(self._rooms[room][user_id]),
        )

    def disconnect(self, room: str, user_id: uuid.UUID, websocket: WebSocket) -> None:
        """Retire un socket ferme et nettoie les entrees vides."""
        user_sockets = self._rooms.get(room, {}).get(user_id)
        if not user_sockets:
            return
        user_sockets.discard(websocket)
        if not user_sockets:
            self._rooms[room].pop(user_id, None)
        if not self._rooms.get(room):
            self._rooms.pop(room, None)
        logger.info("ws disconnect room=%s user=%s", room, user_id)

    async def broadcast(
        self,
        room: str,
        payload: dict,
        *,
        exclude_user: uuid.UUID | None = None,
    ) -> None:
        """Envoie `payload` (JSON) a tous les sockets de la salle."""
        targets = [
            websocket
            for user_id, sockets in self._rooms.get(room, {}).items()
            if user_id != exclude_user
            for websocket in list(sockets)
        ]
        delivered = 0
        for websocket in targets:
            if not await self._safe_send(websocket, payload):
                self._forget(room, websocket)
            else:
                delivered += 1
        logger.info(
            "ws broadcast room=%s type=%s delivered=%d",
            room,
            payload.get("type"),
            delivered,
        )

    async def revoke(self, room: str, user_id: uuid.UUID, *, reason: str) -> None:
        """Ferme immediatement tous les sockets d'un utilisateur dans une salle.

        Utilise a l'exclusion (B-17) et a l'elimination d'equipe (B-18).
        """
        user_sockets = list(self._rooms.get(room, {}).get(user_id, set()))
        if not user_sockets:
            return
        for websocket in user_sockets:
            await self._safe_send(
                websocket,
                {"type": "system", "event": "revoked", "reason": reason},
            )
            await self._safe_close(websocket, WS_CLOSE_FORBIDDEN, reason)
            self.disconnect(room, user_id, websocket)
        logger.info(
            "ws revoke room=%s user=%s reason=%s sockets=%d",
            room,
            user_id,
            reason,
            len(user_sockets),
        )

    def is_connected(self, room: str, user_id: uuid.UUID) -> bool:
        return bool(self._rooms.get(room, {}).get(user_id))

    def _forget(self, room: str, websocket: WebSocket) -> None:
        for user_id, sockets in list(self._rooms.get(room, {}).items()):
            if websocket in sockets:
                self.disconnect(room, user_id, websocket)

    @staticmethod
    async def _safe_send(websocket: WebSocket, payload: dict) -> bool:
        if websocket.application_state is not WebSocketState.CONNECTED:
            return False
        try:
            await websocket.send_json(payload)
            return True
        except RuntimeError, WebSocketDisconnect:
            return False

    @staticmethod
    async def _safe_close(websocket: WebSocket, code: int, reason: str) -> None:
        try:
            await websocket.close(code=code, reason=reason)
        except RuntimeError:
            pass


manager = ConnectionManager()
