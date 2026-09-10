import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TeamMemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    username: str | None = None
    game_role: str | None = None
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=50, description="Nom de l'équipe")
    game_role: str | None = Field(
        None,
        max_length=50,
        description="Rôle en jeu du capitaine (optionnel à la création)",
    )


class TeamUpdateName(BaseModel):
    name: str = Field(
        ..., min_length=2, max_length=50, description="Nouveau nom de l'équipe"
    )


class TeamAssignRole(BaseModel):
    game_role: str = Field(
        ..., min_length=1, max_length=50, description="Rôle en jeu attribué"
    )


class TeamTransferCaptain(BaseModel):
    new_captain_id: uuid.UUID = Field(
        ..., description="ID du membre devenant le nouveau capitaine"
    )


class TeamResponse(BaseModel):
    id: uuid.UUID
    tournament_id: uuid.UUID
    name: str
    captain_id: uuid.UUID
    is_eliminated: bool
    created_at: datetime
    members_count: int = 0
    members: list[TeamMemberResponse] = []

    model_config = ConfigDict(from_attributes=True)


class TeamSimpleResponse(BaseModel):
    id: uuid.UUID
    tournament_id: uuid.UUID
    name: str
    captain_id: uuid.UUID
    is_eliminated: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JoinRequestCreate(BaseModel):
    game_role: str | None = Field(
        None, max_length=50, description="Rôle souhaité par le joueur"
    )


class JoinRequestResponse(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID
    username: str | None = None
    tournament_id: uuid.UUID
    game_role: str | None = None
    status: str
    created_at: datetime
    responded_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
