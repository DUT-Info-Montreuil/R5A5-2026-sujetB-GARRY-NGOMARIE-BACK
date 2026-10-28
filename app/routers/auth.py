from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.config import settings
from app.core.csrf import require_allowed_origin
from app.core.dependencies import CurrentUser, DbSession
from app.core.rate_limit import login_throttle
from app.core.security import new_oauth_secret
from app.services import auth_service, discord_oauth

router = APIRouter(prefix="/auth", tags=["auth"])

FLOW_COOKIE = "oauth_flow"
FLOW_COOKIE_PATH = "/api/v1/auth/discord"
FLOW_TTL_SECONDS = 600


class UserResponse(BaseModel):
    id: str
    username: str
    global_role: str

    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    # No role field on purpose: the role never comes from the client.
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,32}$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


def _user_response(user) -> UserResponse:
    return UserResponse(
        id=str(user.id), username=user.username, global_role=user.global_role
    )


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_minutes * 60,
        path="/",
        **_cookie_options(),
    )


def _cookie_options() -> dict:
    return {
        "httponly": True,
        "secure": settings.session_cookie_secure,
        "samesite": settings.session_cookie_samesite,
    }


@router.get(
    "/discord/login",
    summary="Démarrer la connexion Discord (redirige vers Discord)",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
)
async def discord_login() -> RedirectResponse:
    if not settings.discord_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Connexion Discord non configurée",
        )
    state, verifier = new_oauth_secret(), new_oauth_secret()
    response = RedirectResponse(
        discord_oauth.build_authorization_url(state, verifier),
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        FLOW_COOKIE,
        f"{state}.{verifier}",
        max_age=FLOW_TTL_SECONDS,
        path=FLOW_COOKIE_PATH,
        **{**_cookie_options(), "samesite": "lax"},
    )
    return response


@router.get(
    "/discord/callback",
    summary="Retour de Discord : ouvre la session et pose le cookie",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
)
async def discord_callback(
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    oauth_flow: Annotated[str | None, Cookie(alias=FLOW_COOKIE)] = None,
) -> RedirectResponse:
    parts = oauth_flow.split(".") if oauth_flow else []
    if not code or not state or len(parts) != 2 or state != parts[0]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requête de connexion invalide",
        )
    verifier = parts[1]
    try:
        identity = await discord_oauth.fetch_identity(code, verifier)
    except discord_oauth.DiscordAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Connexion Discord refusée",
        ) from exc

    user = await auth_service.upsert_discord_user(db, identity)
    token = await auth_service.create_session(db, user)
    # Commit before redirecting so the session exists when the browser calls back.
    await db.commit()

    response = RedirectResponse(
        settings.frontend_url, status_code=status.HTTP_302_FOUND
    )
    _set_session_cookie(response, token)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_COOKIE_PATH)
    return response


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_allowed_origin)],
    summary="Créer un compte (identifiant, email, mot de passe) et ouvrir la session",
)
async def register(
    payload: RegisterRequest, db: DbSession, response: Response
) -> UserResponse:
    try:
        user = await auth_service.register_local_user(
            db, payload.username, payload.email, payload.password
        )
    except auth_service.AccountTaken as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identifiant ou email déjà utilisé",
        ) from exc
    token = await auth_service.create_session(db, user)
    await db.commit()
    _set_session_cookie(response, token)
    return _user_response(user)


@router.post(
    "/login",
    response_model=UserResponse,
    dependencies=[Depends(require_allowed_origin)],
    summary="Se connecter avec identifiant ou email et mot de passe",
)
async def login(
    payload: LoginRequest, request: Request, db: DbSession, response: Response
) -> UserResponse:
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}|{payload.identifier.strip().lower()}"
    if login_throttle.is_blocked(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de tentatives, réessayez plus tard",
            headers={"Retry-After": str(settings.login_window_seconds)},
        )
    user = await auth_service.authenticate_local(
        db, payload.identifier, payload.password
    )
    if user is None:
        login_throttle.record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects",
        )
    login_throttle.reset(key)
    token = await auth_service.create_session(db, user)
    await db.commit()
    _set_session_cookie(response, token)
    return _user_response(user)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Utilisateur connecté (session requise)",
)
async def me(current_user: CurrentUser) -> UserResponse:
    return _user_response(current_user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Fermer la session (supprimée côté serveur)",
)
async def logout(
    db: DbSession,
    current_user: CurrentUser,
    session_token: Annotated[
        str | None, Cookie(alias=settings.session_cookie_name)
    ] = None,
) -> Response:
    if session_token:
        await auth_service.delete_session(db, session_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response
