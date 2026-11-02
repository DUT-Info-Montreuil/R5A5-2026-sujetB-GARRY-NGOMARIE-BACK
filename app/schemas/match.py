import uuid
from typing import Literal

from pydantic import BaseModel, Field


class MatchTeam(BaseModel):
    id: uuid.UUID
    name: str


class MatchResponse(BaseModel):
    id: uuid.UUID
    tournament_id: uuid.UUID
    round: int
    match_number: int
    team1_id: uuid.UUID | None
    team2_id: uuid.UUID | None
    team1: MatchTeam | None
    team2: MatchTeam | None
    winner_id: uuid.UUID | None
    team1_score: int
    team2_score: int
    status: Literal["pending", "in_progress", "completed", "forfeit"]
    next_match_id: uuid.UUID | None
    next_match_slot: int | None


class MatchResult(BaseModel):
    team1_score: int = Field(..., ge=0, le=1000, description="Score de l'équipe 1")
    team2_score: int = Field(..., ge=0, le=1000, description="Score de l'équipe 2")


class MatchForfeit(BaseModel):
    forfeiting_team_id: uuid.UUID = Field(
        ..., description="Équipe déclarée forfait ; son adversaire est qualifié"
    )
