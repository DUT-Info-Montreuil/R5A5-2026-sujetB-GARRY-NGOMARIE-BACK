from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.entities import User
from app.services.auth_service import user_for_session

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    session_token: Annotated[
        str | None, Cookie(alias=settings.session_cookie_name)
    ] = None,
) -> User:
    """Resolve the caller from the session cookie, re-read from the DB each time."""
    user = await user_for_session(db, session_token) if session_token else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(current_user: CurrentUser) -> User:
    """Vérifie que l'utilisateur courant possède le rôle global 'admin'."""
    if current_user.global_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès interdit : privilèges administrateur requis",
        )
    return current_user


AdminUser = Annotated[User, Depends(require_admin)]
