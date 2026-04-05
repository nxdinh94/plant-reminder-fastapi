from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ActionTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    icon: str = Field(min_length=1, max_length=80)
    color: str = Field(min_length=1, max_length=16)


class ActionTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    icon: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, min_length=1, max_length=16)


class ActionTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    icon: str
    color: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    version: int
