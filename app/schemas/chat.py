from pydantic import BaseModel, Field
from typing import Literal


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class AgentToolCall(BaseModel):
    name: str


class AgentChatResponse(BaseModel):
    reply: str
    tool_calls: list[AgentToolCall] = Field(default_factory=list)


class PlantDetectionData(BaseModel):
    plant_name: str = Field(min_length=1, max_length=200)
    species: str = Field(min_length=1, max_length=200)
    short_care_guide: str = Field(min_length=1, max_length=1000)


class PlantImageAnalyzeRequest(BaseModel):
    image_base64: str = Field(min_length=20)


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


class PlantDecisionResponse(BaseModel):
    status: Literal["accepted", "rejected", "edited", "invalid"]
    reply: str
    data: PlantDetectionData | None = None
