"""Discord OAuth2, authorization code flow with PKCE.

The backend is the OAuth client: the client secret and the code exchange never
touch the browser. Discord is not an OIDC provider here (no signed ID token), so
the identity comes from `GET /users/@me` called with the freshly issued access
token. Kept apart from the auth service so tests can replace `fetch_identity`
without any network access.
"""

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.core.security import pkce_challenge

AUTH_ENDPOINT = "https://discord.com/oauth2/authorize"
TOKEN_ENDPOINT = "https://discord.com/api/oauth2/token"
ME_ENDPOINT = "https://discord.com/api/users/@me"


class DiscordAuthError(Exception):
    """The Discord exchange failed or returned an identity we refuse."""


@dataclass(frozen=True)
class DiscordIdentity:
    id: str
    username: str


def build_authorization_url(state: str, verifier: str) -> str:
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": "identify",
        "state": state,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


async def fetch_identity(code: str, verifier: str) -> DiscordIdentity:
    async with httpx.AsyncClient(timeout=10) as http:
        token_resp = await http.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.discord_redirect_uri,
                "code_verifier": verifier,
            },
        )
        if token_resp.status_code != 200:
            raise DiscordAuthError("code exchange rejected by Discord")
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise DiscordAuthError("no access_token in Discord response")

        me_resp = await http.get(
            ME_ENDPOINT, headers={"Authorization": f"Bearer {access_token}"}
        )
    if me_resp.status_code != 200:
        raise DiscordAuthError("could not read the Discord profile")

    profile = me_resp.json()
    discord_id, username = profile.get("id"), profile.get("username")
    if not isinstance(discord_id, str) or not discord_id or not username:
        raise DiscordAuthError("Discord profile missing id or username")
    return DiscordIdentity(id=discord_id, username=str(username))
