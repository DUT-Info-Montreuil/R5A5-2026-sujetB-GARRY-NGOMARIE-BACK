from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.core.security import get_password_hash
from app.models.entities import User
from app.routers import auth, teams, tournaments


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Démarrage: initialisation des utilisateurs par défaut si la base est vierge
    async with async_session_factory() as session:
        try:
            admin_check = await session.execute(
                select(User).where(User.username == "admin_master")
            )
            if not admin_check.scalar_one_or_none():
                default_users = [
                    User(
                        username="admin_master",
                        email="admin@tournament.local",
                        hashed_password=get_password_hash("Admin123!"),
                        global_role="admin",
                    ),
                    User(
                        username="player_alice",
                        email="alice@tournament.local",
                        hashed_password=get_password_hash("Alice123!"),
                        global_role="player",
                    ),
                    User(
                        username="player_bob",
                        email="bob@tournament.local",
                        hashed_password=get_password_hash("Bob123!"),
                        global_role="player",
                    ),
                ]
                session.add_all(default_users)
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            import logging

            logging.getLogger(__name__).warning("Seeding users skipped: %s", exc)

    yield
    # Arrêt


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

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

    @app.get("/health", tags=["health"])
    async def health_check():
        return {"status": "ok", "version": settings.app_version}

    return app


app = create_app()
