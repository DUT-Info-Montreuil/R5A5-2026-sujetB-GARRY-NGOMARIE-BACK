from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.csrf import require_trusted_origin
from app.routers import auth, chat, teams, tournaments


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
    )

    app.middleware("http")(require_trusted_origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API v1 routers
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(tournaments.router, prefix="/api/v1")
    app.include_router(teams.tournament_teams_router, prefix="/api/v1")
    app.include_router(teams.teams_router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")

    @app.get("/health", tags=["health"])
    async def health_check():
        return {"status": "ok", "version": settings.app_version}

    return app


app = create_app()
