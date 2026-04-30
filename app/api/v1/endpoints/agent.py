from fastapi import APIRouter, Depends

from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.chat import AgentChatRequest, AgentChatResponse
from app.services.agent_chat import agent


router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatResponse)
def chat_with_agent(
    payload: AgentChatRequest,
    _: User = Depends(get_current_user),
) -> AgentChatResponse:
    return agent.chat(payload.message)
