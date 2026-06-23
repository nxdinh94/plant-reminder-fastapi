from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime


class AgentChatRequest(BaseModel):
    message: str = Field(default="", min_length=0, max_length=1000)
    image_base64: str | None = Field(default=None, min_length=20)
    thread_id: str | None = Field(default=None, min_length=1, max_length=200)
    resume_interrupt: bool = False


class AgentToolCall(BaseModel):
    name: str


class AgentChatResponse(BaseModel):
    reply: str
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    thread_id: str | None = None
    plant_id: str | None = None


class ChatHistoryItem(BaseModel):
    id: str
    thread_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ChatHistoryResponse(BaseModel):
    items: list[ChatHistoryItem] = Field(default_factory=list)
    next_before_created_at: datetime | None = None


class PlantDetectionData(BaseModel):
    plant_name: str = Field(min_length=1, max_length=200)
    species: str = Field(min_length=1, max_length=200)
    note: str = Field(min_length=1, max_length=1000)
    image_path: str = Field(default="")
    overview: str | None = Field(default=None)
    water: str | None = Field(default=None)
    sunlight: str | None = Field(default=None)
    fertilizer: str | None = Field(default=None)
    propagating: str | None = Field(default=None)
    varieties: list[str] = Field(default_factory=list)
    humidity: str | None = Field(default=None)
    temperature: str | None = Field(default=None)
    soil: str | None = Field(default=None)
    running: str | None = Field(default=None)
    potting_and_repotting: str | None = Field(default=None)
    pests_and_diseases: str | None = Field(default=None)
    toxicity: str | None = Field(default=None)
    propagation: str | None = Field(default=None)


class PlantImageAnalyzeRequest(BaseModel):
    image_base64: str = Field(min_length=20)
    message: str | None = Field(default=None)
    thread_id: str | None = Field(default=None, min_length=1, max_length=200)
    is_manual_creation: bool = False


class PlantImageAnalyzeResponse(BaseModel):
    status: Literal["detected", "not_detected"]
    reply: str
    proposal_id: str | None = None
    data: PlantDetectionData | None = None
    decision_required: bool = False
    decision_options: list[Literal["accept", "reject", "edit"]] = Field(default_factory=list)


class PlantDecisionRequest(BaseModel):
    proposal_id: str = Field(min_length=1)
    decision: Literal["accept", "reject", "edit"]
    edited_data: PlantDetectionData | None = None
    thread_id: str | None = Field(default=None, min_length=1, max_length=200)


class PlantDecisionResponse(BaseModel):
    status: Literal["accepted", "rejected", "edited", "invalid"]
    reply: str
    data: PlantDetectionData | None = None
    plant_url: str | None = None
