import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, description="Corps du message")


class MessageResponse(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    author_id: uuid.UUID | None
    author_username: str | None = None
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
