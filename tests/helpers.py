import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import Team, TeamMember, User
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


async def create_team(db: AsyncSession, tournament, name: str, players: int = 5):
    """A team of `players` members (the first is the captain) in `tournament`."""
    users = [await create_user(db, f"{name}-p{i}") for i in range(players)]
    team = Team(
        id=uuid.uuid4(),
        tournament_id=tournament.id,
        name=name,
        captain_id=users[0].id,
    )
    db.add(team)
    await db.flush()
    db.add_all(
        TeamMember(team_id=team.id, user_id=u.id, tournament_id=tournament.id)
        for u in users
    )
    await db.commit()
    return team, users
