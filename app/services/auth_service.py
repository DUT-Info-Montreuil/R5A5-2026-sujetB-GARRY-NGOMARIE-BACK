import re
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    verify_password,
)
from app.models.entities import User, UserSession, utc_now
from app.services.discord_oauth import DiscordIdentity


def role_for_discord_id(discord_id: str) -> str:
    return "admin" if discord_id in settings.admin_discord_id_set else "player"


def role_for_username(username: str) -> str:
    return "admin" if username.lower() in settings.admin_username_set else "player"


class AccountTaken(Exception):
    """Username or email already used by another account."""


async def register_local_user(
    db: AsyncSession, username: str, email: str, password: str
) -> User:
    """Create a password account. The role only ever comes from ADMIN_USERNAMES."""
    email = email.strip().lower()
    taken = (
        await db.execute(
            select(User.id).where(
                or_(func.lower(User.username) == username.lower(), User.email == email)
            )
        )
    ).first()
    if taken:
        raise AccountTaken
    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        global_role=role_for_username(username),
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate_local(
    db: AsyncSession, identifier: str, password: str
) -> User | None:
    """Return the user for a username-or-email plus password, else None.

    The password is always verified (against a dummy hash when the account is
    unknown or has no password) so the outcome does not leak which case it was.
    """
    ident = identifier.strip().lower()
    user = (
        await db.execute(
            select(User).where(
                or_(func.lower(User.username) == ident, User.email == ident)
            )
        )
    ).scalar_one_or_none()
    if not verify_password(password, user.password_hash if user else None) or not user:
        return None
    # Recomputed at every login, like the Discord ids: removing a name demotes it.
    user.global_role = role_for_username(user.username)
    await db.flush()
    return user


async def _free_username(db: AsyncSession, wanted: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_.-]", "", wanted)[:40] or "player"
    candidate = base
    # Case-insensitive, like password login: two names differing only by case
    # would make a login by name ambiguous.
    while (
        await db.execute(
            select(User.id).where(func.lower(User.username) == candidate.lower())
        )
    ).first():
        candidate = f"{base}-{secrets.token_hex(2)}"
    return candidate


async def upsert_discord_user(db: AsyncSession, identity: DiscordIdentity) -> User:
    """Find the user for this Discord account or create a player.

    The role is recomputed from ADMIN_DISCORD_IDS on every login, so removing an
    id from the allowlist demotes the account at its next login.
    """
    user = (
        await db.execute(select(User).where(User.discord_id == identity.id))
    ).scalar_one_or_none()
    role = role_for_discord_id(identity.id)
    if user is None:
        user = User(
            discord_id=identity.id,
            username=await _free_username(db, identity.username),
            global_role=role,
        )
        db.add(user)
    else:
        user.global_role = role
    await db.flush()
    return user


async def create_session(db: AsyncSession, user: User) -> str:
    """Store a session row and return the raw token for the cookie."""
    now = utc_now()
    await db.execute(
        delete(UserSession).where(
            UserSession.user_id == user.id, UserSession.expires_at <= now
        )
    )
    token = new_session_token()
    db.add(
        UserSession(
            token_hash=hash_session_token(token),
            user_id=user.id,
            expires_at=now + timedelta(minutes=settings.session_ttl_minutes),
        )
    )
    await db.flush()
    return token


async def user_for_session(db: AsyncSession, token: str) -> User | None:
    stmt = (
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == hash_session_token(token),
            UserSession.expires_at > utc_now(),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_session(db: AsyncSession, token: str) -> None:
    await db.execute(
        delete(UserSession).where(UserSession.token_hash == hash_session_token(token))
    )
