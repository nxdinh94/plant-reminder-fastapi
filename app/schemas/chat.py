from pydantic import BaseModel, Field


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class AgentToolCall(BaseModel):
    name: str


class AgentChatResponse(BaseModel):
    reply: str
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
