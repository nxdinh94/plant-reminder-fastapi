from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreate(BaseModel):
    plant_id: str = Field(min_length=1, max_length=36)
    action_type_id: str = Field(min_length=1, max_length=36)
    frequency_type: str = Field(min_length=1, max_length=32)
    frequency_days: int | None = None
    days_of_week: list[str] | None = None
    scheduled_time: time
    note: str | None = None
    last_completed_at: datetime | None = None
    next_due_at: datetime | None = None
    start_date: date | None = None


class ScheduleUpdate(BaseModel):
    plant_id: str | None = Field(default=None, min_length=1, max_length=36)
    action_type_id: str | None = Field(default=None, min_length=1, max_length=36)
    frequency_type: str | None = Field(default=None, min_length=1, max_length=32)
    frequency_days: int | None = None
    days_of_week: list[str] | None = None
    scheduled_time: time | None = None
    note: str | None = None
    last_completed_at: datetime | None = None
    next_due_at: datetime | None = None
    start_date: date | None = None


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    plant_id: str
    action_type_id: str
    frequency_type: str
    frequency_days: int | None
    days_of_week: list[str] | None
    scheduled_time: time
    note: str | None
    last_completed_at: datetime | None
    next_due_at: datetime | None
    start_date: date | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    version: int


class ScheduleDeltaItem(BaseModel):
    id: str
    plant_id: str
    action_type_id: str
    frequency_type: str
    frequency_days: int | None
    days_of_week: list[str] | None
    scheduled_time: time
    next_due_at: datetime | None
    updated_at: datetime
    version: int


class ScheduleDeltaTombstone(BaseModel):
    id: str
    deleted_at: datetime
    version: int


class ScheduleDeltaResponse(BaseModel):
    server_time: datetime
    since: datetime | None = None
    next_cursor: datetime
    schedules: list[ScheduleDeltaItem]
    tombstones: list[ScheduleDeltaTombstone]
