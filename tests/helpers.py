import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import User
from app.services.auth_service import create_session

TRUSTED_ORIGIN = settings.allowed_origins[0]


async def session_headers(db: AsyncSession, user_id: uuid.UUID | str) -> dict[str, str]:
    """Headers of a logged-in browser: real session row + cookie + trusted Origin."""
    user = await db.get(User, uuid.UUID(str(user_id)))
    token = await create_session(db, user)
    await db.commit()
    return {
        "Cookie": f"{settings.session_cookie_name}={token}",
        "Origin": TRUSTED_ORIGIN,
    }


async def create_user(db: AsyncSession, username: str, role: str = "player") -> User:
    user = User(
        id=uuid.uuid4(),
        username=username,
        discord_id=uuid.uuid4().hex,
        global_role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
