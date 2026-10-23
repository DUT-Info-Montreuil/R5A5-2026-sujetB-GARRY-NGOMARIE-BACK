"""Local accounts: users.email + users.password_hash, discord_id becomes optional

Revision ID: 0004_local_accounts
Revises: 0003_discord_auth_sessions
Create Date: 2026-09-24 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_local_accounts"
down_revision: str | Sequence[str] | None = "0003_discord_auth_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=255)))
    op.add_column("users", sa.Column("password_hash", sa.String(length=255)))
    with op.batch_alter_table("users") as batch:
        batch.alter_column("discord_id", nullable=True)
        batch.create_check_constraint(
            "check_user_has_credential",
            "discord_id IS NOT NULL OR password_hash IS NOT NULL",
        )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    # Local accounts have no Discord identity: give them the unmatchable
    # placeholder used by 0003 so discord_id can be NOT NULL again.
    op.execute(
        "UPDATE users SET discord_id = "
        "'legacy' || substr(replace(CAST(id AS VARCHAR), '-', ''), 1, 26) "
        "WHERE discord_id IS NULL"
    )
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("check_user_has_credential", type_="check")
        batch.alter_column("discord_id", nullable=False)
        batch.drop_column("password_hash")
        batch.drop_column("email")
