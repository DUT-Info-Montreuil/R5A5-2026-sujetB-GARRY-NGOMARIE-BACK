"""Initial schema: users, tournaments, teams, team_members, matches, messages

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-09-10 14:26:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001_initial_schema'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Users
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('global_role', sa.String(length=20), server_default='player', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("global_role IN ('player', 'admin')", name='check_user_global_role'),
        sa.UniqueConstraint('username', name='uq_users_username'),
        sa.UniqueConstraint('email', name='uq_users_email')
    )
    op.create_index('ix_users_username', 'users', ['username'])
    op.create_index('ix_users_email', 'users', ['email'])

    # 2. Tournaments
    op.create_table(
        'tournaments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('game', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=30), server_default='registration_open', nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('registration_closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('registration_open', 'registration_closed', 'running', 'finished')", name='check_tournament_status'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL')
    )
    op.create_index('ix_tournaments_status', 'tournaments', ['status'])

    # 3. Teams
    op.create_table(
        'teams',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('tournament_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('captain_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('is_eliminated', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['captain_id'], ['users.id'], ondelete='RESTRICT'),
        sa.UniqueConstraint('tournament_id', 'name', name='uq_team_tournament_name')
    )
    op.create_index('ix_teams_tournament_id', 'teams', ['tournament_id'])
    op.create_index('ix_teams_captain_id', 'teams', ['captain_id'])

    # 4. Team Members (Règle B-07: Un joueur dans au plus 1 équipe par tournoi)
    op.create_table(
        'team_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tournament_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('game_role', sa.String(length=50), nullable=True),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('tournament_id', 'user_id', name='uq_player_per_tournament'),
        sa.UniqueConstraint('team_id', 'user_id', name='uq_team_member')
    )
    op.create_index('ix_team_members_team_id', 'team_members', ['team_id'])
    op.create_index('ix_team_members_user_id', 'team_members', ['user_id'])
    op.create_index('ix_team_members_tournament_id', 'team_members', ['tournament_id'])

    # 5. Matches (Arbre de tournoi)
    op.create_table(
        'matches',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('tournament_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('match_number', sa.Integer(), nullable=False),
        sa.Column('team1_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('team2_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('winner_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('team1_score', sa.Integer(), server_default='0', nullable=False),
        sa.Column('team2_score', sa.Integer(), server_default='0', nullable=False),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('next_match_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('next_match_slot', sa.Integer(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'in_progress', 'completed', 'forfeit')", name='check_match_status'),
        sa.CheckConstraint("next_match_slot IN (1, 2)", name='check_next_match_slot'),
        sa.ForeignKeyConstraint(['tournament_id'], ['tournaments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team1_id'], ['teams.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['team2_id'], ['teams.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['winner_id'], ['teams.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['next_match_id'], ['matches.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('tournament_id', 'round', 'match_number', name='uq_match_tournament_round_number')
    )
    op.create_index('ix_matches_tournament_id', 'matches', ['tournament_id'])

    # 6. Messages (Espace d'échange privé)
    op.create_table(
        'messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('author_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL')
    )
    op.create_index('ix_messages_team_created', 'messages', ['team_id', 'created_at'])


def downgrade() -> None:
    op.drop_table('messages')
    op.drop_table('matches')
    op.drop_table('team_members')
    op.drop_table('teams')
    op.drop_table('tournaments')
    op.drop_table('users')
