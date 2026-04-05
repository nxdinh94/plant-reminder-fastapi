from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PlantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    species: str = Field(min_length=1, max_length=120)
    potted_date: date | None = None
    image_path: str | None = Field(default=None, max_length=1024)
    note: str | None = None
    is_paused: bool = False


class PlantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    species: str | None = Field(default=None, min_length=1, max_length=120)
    potted_date: date | None = None
    image_path: str | None = Field(default=None, max_length=1024)
    note: str | None = None
    is_paused: bool | None = None


class PlantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    species: str
    potted_date: date | None
    image_path: str | None
    note: str | None
    is_paused: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    version: int
