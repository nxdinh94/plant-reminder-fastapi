from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class TaskCompletionCreate(BaseModel):
    schedule_id: str = Field(min_length=1, max_length=36)
    completion_date: date
    completed_at: datetime | None = None


class TaskCompletionUpdate(BaseModel):
    completion_date: date | None = None
    completed_at: datetime | None = None


class TaskCompletionToggleRequest(BaseModel):
    completed: bool


class TaskCompletionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    schedule_id: str
    completion_date: date
    completed_at: datetime
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    version: int
