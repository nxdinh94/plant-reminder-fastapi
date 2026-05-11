from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PlantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    species: str = Field(max_length=120, default="")
    potted_date: date | None = None
    image_path: str | None = Field(default=None, max_length=1024)
    note: str | None = None
    is_paused: bool = False
    overview: str | None = None
    water: str | None = None
    sunlight: str | None = None
    fertilizer: str | None = None
    propagating: str | None = None
    varieties: str | None = None
    humidity: str | None = None
    temperature: str | None = None
    soil: str | None = None
    running: str | None = None
    potting_and_repotting: str | None = None
    pests_and_diseases: str | None = None
    toxicity: str | None = None
    propagation: str | None = None


class PlantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    species: str | None = Field(default=None, max_length=120)
    potted_date: date | None = None
    image_path: str | None = Field(default=None, max_length=1024)
    note: str | None = None
    is_paused: bool | None = None
    overview: str | None = None
    water: str | None = None
    sunlight: str | None = None
    fertilizer: str | None = None
    propagating: str | None = None
    varieties: str | None = None
    humidity: str | None = None
    temperature: str | None = None
    soil: str | None = None
    running: str | None = None
    potting_and_repotting: str | None = None
    pests_and_diseases: str | None = None
    toxicity: str | None = None
    propagation: str | None = None


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
    overview: str | None = None
    water: str | None = None
    sunlight: str | None = None
    fertilizer: str | None = None
    propagating: str | None = None
    varieties: str | None = None
    humidity: str | None = None
    temperature: str | None = None
    soil: str | None = None
    running: str | None = None
    potting_and_repotting: str | None = None
    pests_and_diseases: str | None = None
    toxicity: str | None = None
    propagation: str | None = None
