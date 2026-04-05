from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.path_policy import normalize_image_path


class TimelineCreate(BaseModel):
    plant_id: str = Field(min_length=1, max_length=36)
    image_path: str | None = Field(default=None, max_length=1024)
    description: str | None = None

    @field_validator("image_path")
    @classmethod
    def validate_image_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_image_path(value)


class TimelineUpdate(BaseModel):
    image_path: str | None = Field(default=None, max_length=1024)
    description: str | None = None

    @field_validator("image_path")
    @classmethod
    def validate_image_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_image_path(value)


class TimelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    plant_id: str
    image_path: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    version: int
