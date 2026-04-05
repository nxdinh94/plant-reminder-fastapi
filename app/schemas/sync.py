from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SyncEntityCapability(BaseModel):
    name: str
    supports_push: bool = True
    supports_pull: bool = True
    supports_tombstones: bool = True


class SyncIdempotencyCapability(BaseModel):
    request_header: str = "X-Request-ID"
    operation_header: str = "X-Operation-ID"
    required_for_mutations: bool = True


class SyncCapabilitiesResponse(BaseModel):
    server_time: datetime
    api_base_path: str
    api_version: str
    entities: list[SyncEntityCapability]
    idempotency: SyncIdempotencyCapability = Field(default_factory=SyncIdempotencyCapability)


class SyncBootstrapResponse(BaseModel):
    server_time: datetime
    user_id: str
    baseline_cursor: datetime
    cursor_field: str = "updated_at"
    capabilities_path: str


class SyncPushOperation(BaseModel):
    operation_id: str = Field(min_length=1, max_length=128)
    entity_type: str = Field(min_length=1, max_length=64)
    operation: Literal["create", "update", "upsert", "delete"]
    entity_id: str | None = Field(default=None, max_length=36)
    payload: dict[str, Any] = Field(default_factory=dict)


class SyncPushRequest(BaseModel):
    operations: list[SyncPushOperation] = Field(default_factory=list)


class SyncPushOperationResult(BaseModel):
    operation_id: str
    entity_type: str
    entity_id: str | None = None
    status: Literal["applied", "duplicate", "failed"]
    retryable: bool = False
    error: str | None = None


class SyncPushResponse(BaseModel):
    server_time: datetime
    results: list[SyncPushOperationResult]


class SyncPullResponse(BaseModel):
    server_time: datetime
    since: datetime | None = None
    next_cursor: datetime
    changes: dict[str, list[dict[str, Any]]]
    tombstones: dict[str, list[dict[str, Any]]]
