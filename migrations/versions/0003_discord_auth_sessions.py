"""Discord login: users.discord_id, drop users.hashed_password and email, add user_sessions

Revision ID: 0003_discord_auth_sessions
Revises: ac1b8e20818d
Create Date: 2026-09-24 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_discord_auth_sessions"
down_revision: str | Sequence[str] | None = "ac1b8e20818d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("discord_id", sa.String(length=32)))
    # Accounts created by the old password login have no Discord identity. They
    # get an unmatchable placeholder so they can never be logged into: it is not
    # all digits, so it never equals a Discord snowflake, and it fits in 32 chars.
    op.execute(
        "UPDATE users SET discord_id = "
        "'legacy' || substr(replace(CAST(id AS VARCHAR), '-', ''), 1, 26)"
    )
    op.drop_index("ix_users_email", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("discord_id", nullable=False)
        batch.drop_column("hashed_password")
        batch.drop_column("email")
    op.create_index("ix_users_discord_id", "users", ["discord_id"], unique=True)

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_token_hash", table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_index("ix_users_discord_id", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "hashed_password",
                sa.String(length=255),
                nullable=False,
                server_default="!",
            )
        )
        batch.add_column(sa.Column("email", sa.String(length=255)))
    op.execute("UPDATE users SET email = discord_id || '@legacy.invalid'")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("email", nullable=False)
        batch.drop_column("discord_id")
    # ac1b8e20818d replaced the unique constraint by this unique index.
    op.create_index("ix_users_email", "users", ["email"], unique=True)
