import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    global_role: Mapped[str] = mapped_column(String(20), nullable=False, default="player")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        CheckConstraint("global_role IN ('player', 'admin')", name="check_user_global_role"),
    )

    # Relations
    captained_teams: Mapped[list[Team]] = relationship("Team", back_populates="captain", foreign_keys="Team.captain_id")
    memberships: Mapped[list[TeamMember]] = relationship("TeamMember", back_populates="user", cascade="all, delete-orphan")
    messages: Mapped[list[Message]] = relationship("Message", back_populates="author")


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    game: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="registration_open", index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    registration_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('registration_open', 'registration_closed', 'running', 'finished')",
            name="check_tournament_status",
        ),
    )

    # Relations
    teams: Mapped[list[Team]] = relationship("Team", back_populates="tournament", cascade="all, delete-orphan")
    matches: Mapped[list[Match]] = relationship("Match", back_populates="tournament", cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    captain_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    is_eliminated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("tournament_id", "name", name="uq_team_tournament_name"),
    )

    # Relations
    tournament: Mapped[Tournament] = relationship("Tournament", back_populates="teams")
    captain: Mapped[User] = relationship("User", back_populates="captained_teams", foreign_keys=[captain_id])
    members: Mapped[list[TeamMember]] = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")
    messages: Mapped[list[Message]] = relationship("Message", back_populates="team", cascade="all, delete-orphan")


class TeamMember(Base):
    __tablename__ = "team_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tournament_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    game_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    __table_args__ = (
        # Règle B-07: un joueur est dans au plus une équipe par tournoi
        UniqueConstraint("tournament_id", "user_id", name="uq_player_per_tournament"),
        UniqueConstraint("team_id", "user_id", name="uq_team_member"),
    )

    # Relations
    team: Mapped[Team] = relationship("Team", back_populates="members")
    user: Mapped[User] = relationship("User", back_populates="memberships")


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    match_number: Mapped[int] = mapped_column(Integer, nullable=False)

    team1_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    team2_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    winner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)

    team1_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    team2_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    next_match_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("matches.id", ondelete="SET NULL"), nullable=True)
    next_match_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("tournament_id", "round", "match_number", name="uq_match_tournament_round_number"),
        CheckConstraint("status IN ('pending', 'in_progress', 'completed', 'forfeit')", name="check_match_status"),
        CheckConstraint("next_match_slot IN (1, 2)", name="check_next_match_slot"),
    )

    # Relations
    tournament: Mapped[Tournament] = relationship("Tournament", back_populates="matches")
    team1: Mapped[Team | None] = relationship("Team", foreign_keys=[team1_id])
    team2: Mapped[Team | None] = relationship("Team", foreign_keys=[team2_id])
    winner: Mapped[Team | None] = relationship("Team", foreign_keys=[winner_id])
    next_match: Mapped[Match | None] = relationship("Match", remote_side=[id], foreign_keys=[next_match_id])


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    # Relations
    team: Mapped[Team] = relationship("Team", back_populates="messages")
    author: Mapped[User | None] = relationship("User", back_populates="messages")
