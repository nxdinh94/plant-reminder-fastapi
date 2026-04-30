from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

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


@router.post("/chat/stream")
async def chat_with_agent_stream(
    payload: AgentChatRequest,
    _: User = Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        agent.chat_stream(payload.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
