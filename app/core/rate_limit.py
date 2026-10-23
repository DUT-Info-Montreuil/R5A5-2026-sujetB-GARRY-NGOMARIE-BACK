import time
from collections import defaultdict

from app.core.config import settings


class LoginThrottle:
    """In-memory failed-login counter, keyed by (client ip, username).

    Per-process only: with several API workers each keeps its own count, so the
    effective limit is multiplied by the worker count. Keyed on the ip as well so
    an attacker cannot lock a victim out of their own account.
    """

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = defaultdict(list)

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - settings.login_window_seconds
        recent = [t for t in self._failures[key] if t > cutoff]
        self._failures[key] = recent
        return recent

    def is_blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= settings.login_max_failures

    def record_failure(self, key: str) -> None:
        self._recent(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)

    def clear(self) -> None:
        self._failures.clear()


login_throttle = LoginThrottle()
