from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
import logging

from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.chat import (
    AgentChatRequest,
    AgentChatResponse,
    PlantDecisionRequest,
    PlantDecisionResponse,
    PlantImageAnalyzeRequest,
    PlantImageAnalyzeResponse,
)
from app.services.agent_chat import agent


router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=AgentChatResponse)
def chat_with_agent(
    payload: AgentChatRequest,
    _: User = Depends(get_current_user),
) -> AgentChatResponse:
    return agent.chat(payload.message)


@router.post("/plant-image/analyze", response_model=PlantImageAnalyzeResponse)
def analyze_plant_image(
    payload: PlantImageAnalyzeRequest,
    _: User = Depends(get_current_user),
) -> PlantImageAnalyzeResponse:
    preview = payload.image_base64[:200]
    logger.info(
        "Plant image analyze request body: image_base64_len=%d preview=%r",
        len(payload.image_base64),
        preview,
    )
    result = agent.analyze_plant_image(payload.image_base64)
    logger.info("Plant image analyze response body: %s", result.model_dump_json())
    return result


@router.post("/plant-image/decision", response_model=PlantDecisionResponse)
def apply_plant_decision(
    payload: PlantDecisionRequest,
    _: User = Depends(get_current_user),
) -> PlantDecisionResponse:
    return agent.apply_plant_decision(payload.proposal_id, payload.decision, payload.edited_data)


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
