from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import select

from app.core.dependencies import DbSession
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.entities import User

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRegister(BaseModel):
    username: str
    email: EmailStr
    password: str
    global_role: str = "player"


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    global_role: str

    model_config = ConfigDict(from_attributes=True)


@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> TokenResponse:
    # Authentification par username ou email
    stmt = select(User).where(
        (User.username == form_data.username) | (User.email == form_data.username)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.global_role}
    )
    return TokenResponse(access_token=access_token)


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    payload: UserRegister,
    db: DbSession,
) -> UserResponse:
    stmt = select(User).where(
        (User.username == payload.username) | (User.email == payload.email)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nom d'utilisateur ou adresse email déjà utilisé",
        )

    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        global_role=payload.global_role
        if payload.global_role in ("player", "admin")
        else "player",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        global_role=user.global_role,
    )


@router.get("/users", response_model=list[UserResponse])
async def list_users(db: DbSession) -> list[UserResponse]:
    stmt = select(User).order_by(User.created_at.asc())
    result = await db.execute(stmt)
    users = result.scalars().all()
    return [
        UserResponse(
            id=str(u.id),
            username=u.username,
            email=u.email,
            global_role=u.global_role,
        )
        for u in users
    ]


@router.post("/dev-token/{user_id}", response_model=TokenResponse)
async def dev_token_for_user(user_id: str, db: DbSession) -> TokenResponse:
    import uuid

    try:
        uid = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="UUID invalide") from exc

    user = await db.get(User, uid)
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")

    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.global_role}
    )
    return TokenResponse(access_token=access_token)
