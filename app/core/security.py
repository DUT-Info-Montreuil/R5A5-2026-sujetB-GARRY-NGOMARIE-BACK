import base64
import hashlib
import secrets

from pwdlib import PasswordHash


def new_session_token() -> str:
    """Opaque random value sent to the browser; only its hash is stored."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_oauth_secret() -> str:
    return secrets.token_urlsafe(32)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


_hasher = PasswordHash.recommended()
# Verified against when the account does not exist, so that "unknown user" and
# "wrong password" cost the same and cannot be told apart by timing.
_DUMMY_HASH = _hasher.hash("timing-equalizer")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    return _hasher.verify(password, password_hash or _DUMMY_HASH) and bool(
        password_hash
    )
