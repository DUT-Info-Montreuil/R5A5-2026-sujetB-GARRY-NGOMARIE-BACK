from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Tournament Platform API"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://app_user:app_password@db:5432/app_db"

    # Discord OAuth2 (authorization code flow, handled by the backend)
    discord_client_id: str = ""
    discord_client_secret: str = ""
    # Must match a redirect registered in the Discord developer portal.
    discord_redirect_uri: str = "http://localhost:8000/api/v1/auth/discord/callback"

    # Comma-separated Discord user ids (snowflakes) that get the admin role.
    admin_discord_ids: str = ""

    # Comma-separated usernames of password accounts that get the admin role.
    # Register the admin account right after deploying: until then the name is free.
    admin_usernames: str = ""

    # Password login throttle: failures allowed per (client ip, username) per window.
    login_max_failures: int = 5
    login_window_seconds: int = 900

    # Cookie session
    session_cookie_name: str = "session"
    session_ttl_minutes: int = 60 * 24
    # Secure cookies are only sent over HTTPS (browsers exempt localhost).
    session_cookie_secure: bool = True
    # "lax" is enough when front and API share a registrable domain; a
    # cross-site deployment needs "none" (which requires secure=True).
    session_cookie_samesite: str = "lax"

    # Where the browser is sent after a successful login.
    frontend_url: str = "http://localhost:5173"

    # CORS + CSRF origin check
    allowed_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Chat / temps reel
    chat_message_max_length: int = 2000
    chat_history_limit: int = 200

    @property
    def admin_username_set(self) -> frozenset[str]:
        return frozenset(
            u.strip().lower() for u in self.admin_usernames.split(",") if u.strip()
        )

    @property
    def admin_discord_id_set(self) -> frozenset[str]:
        return frozenset(
            i.strip() for i in self.admin_discord_ids.split(",") if i.strip()
        )


settings = Settings()
