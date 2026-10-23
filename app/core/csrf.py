from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.core.config import settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def require_trusted_origin(request: Request, call_next):
    """Reject cookie-authenticated state changes that do not come from our front.

    SameSite already blocks most cross-site sends; this is the second layer and
    does not depend on the browser honouring SameSite. A missing Origin on an
    unsafe method with a session cookie is refused too.
    """
    if (
        request.method not in SAFE_METHODS
        and request.cookies.get(settings.session_cookie_name)
        and request.headers.get("origin") not in settings.allowed_origins
    ):
        return JSONResponse(
            status_code=403, content={"detail": "Origine non autorisée"}
        )
    return await call_next(request)


def require_allowed_origin(request: Request) -> None:
    """Dependency for the anonymous login/register POSTs, which carry no cookie yet.

    The middleware above only guards requests that already hold a session; this
    stops a foreign page from logging a visitor into an attacker's account.
    """
    if request.headers.get("origin") not in settings.allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Origine non autorisée"
        )
