import app.models  # noqa: F401
from app.core.database import Base


def test_models_metadata_registration():
    table_names = set(Base.metadata.tables.keys())
    expected_tables = {
        "users",
        "tournaments",
        "teams",
        "team_members",
        "matches",
        "messages",
        "team_join_requests",
    }
    assert expected_tables.issubset(table_names)


def test_unique_constraints_defined():
    # Test uniqueness constraint on team_members (one team per tournament per player)
    tm_table = Base.metadata.tables["team_members"]
    uq_names = {c.name for c in tm_table.constraints}
    assert "uq_player_per_tournament" in uq_names
    assert "uq_team_member" in uq_names

    # Test teams constraints
    teams_table = Base.metadata.tables["teams"]
    t_uq_names = {c.name for c in teams_table.constraints}
    assert "uq_team_tournament_name" in t_uq_names


def test_check_constraints_defined():
    users_table = Base.metadata.tables["users"]
    user_constraints = {c.name for c in users_table.constraints}
    assert "check_user_global_role" in user_constraints

    tournaments_table = Base.metadata.tables["tournaments"]
    tourn_constraints = {c.name for c in tournaments_table.constraints}
    assert "check_tournament_status" in tourn_constraints
