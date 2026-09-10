import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TournamentCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Nom du tournoi")
    game: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="Jeu supporté (ex: LoL, CS2, Valorant)",
    )


class TournamentResponse(BaseModel):
    id: uuid.UUID
    name: str
    game: str
    status: str
    created_by: uuid.UUID | None
    created_at: datetime
    registration_closed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
