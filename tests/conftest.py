"""Shared fixtures for the backend test suite.

V0 harness. The backend application does not exist yet (see ``feature.md``).
Every fixture that would need the app is a placeholder: it calls
``pytest.skip`` so any test requesting it is reported as skipped rather than
failing on an import error.

As ``app/`` is built, replace each placeholder body with a real
implementation. The security tests in ``tests/security/`` are already written
against these fixture names and the access rules in ``context.md`` section 8,
so they start exercising the code as soon as the fixtures are wired.
"""

import pytest

_NOT_IMPLEMENTED = "V0 harness: backend not implemented yet"


@pytest.fixture
def auth():
    """Return a helper that turns a bearer token into a request headers dict.

    Not a placeholder: usable as soon as the app exists.
    """

    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _headers


@pytest.fixture
def client():
    """HTTP test client bound to the FastAPI app.

    Replace with ``TestClient(app)`` (or an async client) once ``app`` exists.
    """
    pytest.skip(_NOT_IMPLEMENTED)


# --- Identities -------------------------------------------------------------
# Bearer tokens for callers in each role. ``context.md`` section 5.


@pytest.fixture
def admin_token():
    """Token for an authenticated administrator."""
    pytest.skip(_NOT_IMPLEMENTED)


@pytest.fixture
def player_token():
    """Token for an authenticated player with no team."""
    pytest.skip(_NOT_IMPLEMENTED)


@pytest.fixture
def captain_token():
    """Token for the player who captains ``team`` (in ``open_tournament``).

    The same user also captains ``eliminated_team`` in ``running_tournament`` --
    allowed, since B-07 scopes "one team" to a single tournament.
    """
    pytest.skip(_NOT_IMPLEMENTED)


@pytest.fixture
def other_player_token():
    """Token for a player who is a member of a different team in
    ``open_tournament`` and is never a member of ``team``.
    """
    pytest.skip(_NOT_IMPLEMENTED)


@pytest.fixture
def excluded_player_token():
    """Token for a player who was a member of ``team`` and has been excluded."""
    pytest.skip(_NOT_IMPLEMENTED)


# --- Tournaments in each lifecycle state ----------------------------------
# ``context.md`` section 6. Each fixture yields an object exposing ``.id``.


@pytest.fixture
def open_tournament():
    """A tournament in state ``registration open``."""
    pytest.skip(_NOT_IMPLEMENTED)


@pytest.fixture
def closed_tournament():
    """A tournament in state ``registration closed`` (>= 2 engaged teams)."""
    pytest.skip(_NOT_IMPLEMENTED)


@pytest.fixture
def running_tournament():
    """A tournament in state ``running`` with a built bracket."""
    pytest.skip(_NOT_IMPLEMENTED)


@pytest.fixture
def single_team_tournament():
    """A tournament in ``registration open`` with exactly one engaged team."""
    pytest.skip(_NOT_IMPLEMENTED)


# --- Teams --------------------------------------------------------------------
# Each fixture yields an object exposing ``.id`` and ``.tournament_id``.


@pytest.fixture
def team():
    """A team in ``open_tournament`` with fewer than 5 members.

    Captain is the user behind ``captain_token``; it also holds the user
    behind ``excluded_player_token`` as an excluded (former) member.
    """
    pytest.skip(_NOT_IMPLEMENTED)


@pytest.fixture
def full_team():
    """A team in ``open_tournament`` with exactly 5 members (roster full).

    Captain identity is unspecified; only the full roster matters.
    """
    pytest.skip(_NOT_IMPLEMENTED)


@pytest.fixture
def eliminated_team():
    """A team in ``running_tournament`` that has been eliminated.

    Captained by the user behind ``captain_token``.
    """
    pytest.skip(_NOT_IMPLEMENTED)


# --- Matches ----------------------------------------------------------------
# Each fixture yields an object exposing ``.id``.


@pytest.fixture
def ready_match():
    """A match in ``running_tournament`` where both teams are known."""
    pytest.skip(_NOT_IMPLEMENTED)


@pytest.fixture
def pending_match():
    """A match in ``running_tournament`` where one team is not yet known."""
    pytest.skip(_NOT_IMPLEMENTED)
