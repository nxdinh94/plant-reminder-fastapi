from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProfileSettingsUpdate(BaseModel):
    points: int | None = None
    streak_day: int | None = None
    theme: str | None = Field(default=None, min_length=1, max_length=32)
    start_of_week: str | None = Field(default=None, max_length=16)
    device_preferences: dict[str, Any] | None = None


class ProfileSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    points: int
    streak_day: int
    theme: str
    start_of_week: str | None
    device_preferences: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    version: int
