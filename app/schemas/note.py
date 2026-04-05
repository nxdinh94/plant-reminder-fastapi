from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.path_policy import normalize_image_path


class NoteCreate(BaseModel):
    plant_id: str = Field(min_length=1, max_length=36)
    entry_date: date
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    image_paths: list[str] = Field(default_factory=list)

    @field_validator("image_paths")
    @classmethod
    def validate_image_paths(cls, values: list[str]) -> list[str]:
        return [normalize_image_path(value) for value in values]


class NoteUpdate(BaseModel):
    entry_date: date | None = None
    content: str | None = Field(default=None, min_length=1)
    tags: list[str] | None = None
    image_paths: list[str] | None = None

    @field_validator("image_paths")
    @classmethod
    def validate_image_paths(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return [normalize_image_path(value) for value in values]


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    plant_id: str
    entry_date: date
    content: str
    tags: list[str]
    image_paths: list[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    version: int
