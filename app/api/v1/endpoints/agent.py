from fastapi import APIRouter, Depends, Request
from datetime import datetime, timezone
import uuid
from fastapi.responses import StreamingResponse
import logging
from sqlalchemy import and_, desc
from sqlalchemy.orm import Session
from sqlalchemy.exc import ProgrammingError

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.plant import Plant
from app.models.chat_message import ChatMessage
from app.models.user import User
from app.schemas.chat import (
    AgentChatRequest,
    AgentChatResponse,
    ChatHistoryItem,
    ChatHistoryResponse,
    PlantDecisionRequest,
    PlantDecisionResponse,
    PlantImageAnalyzeRequest,
    PlantImageAnalyzeResponse,
)
from app.services.agent_chat import agent


router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger(__name__)


def _log_chatbot_api_error(
    *,
    api_name: str,
    request: Request | None,
    user_id: str | None = None,
    extra: str | None = None,
) -> None:
    method = request.method if request is not None else "unknown"
    path = request.url.path if request is not None else "unknown"
    request_id = request.headers.get("x-request-id") if request is not None else None
    logger.exception(
        "Chatbot API error: api=%s method=%s path=%s request_id=%s user_id=%s extra=%s",
        api_name,
        method,
        path,
        request_id,
        user_id,
        extra,
    )


@router.post("/chat", response_model=AgentChatResponse)
def chat_with_agent(
    payload: AgentChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AgentChatResponse:
    try:
        if payload.image_base64:
            logger.info(
                "Agent chat request body: message=%r image_base64_len=%d image_base64_preview=%r thread_id=%r",
                payload.message,
                len(payload.image_base64),
                payload.image_base64[:200],
                payload.thread_id,
            )
        else:
            logger.info(
                "Agent chat request body: message=%r image_base64=None thread_id=%r",
                payload.message,
                payload.thread_id,
            )

        thread_id = payload.thread_id or str(uuid.uuid4())

        # Persist user message (skip if empty image-only message)
        if payload.message.strip():
            try:
                message_created_at = datetime.now(timezone.utc)
                user_message = ChatMessage(
                    user_id=current_user.id,
                    thread_id=thread_id,
                    role="user",
                    content=payload.message,
                    created_at=message_created_at,
                )
                db.add(user_message)
                db.commit()
            except ProgrammingError:
                db.rollback()
                logger.exception("chat history persistence failed for user message; continuing without persistence")

        accept_language = request.headers.get("accept-language", "en")
        language = "vi" if "vi" in accept_language.lower() else "en"

        timezone_str = request.headers.get("time-zone", "UTC")
        local_time_str = request.headers.get("local-time", None)

        response = agent.chat(
            payload.message,
            image_base64=payload.image_base64,
            thread_id=thread_id,
            language=language,
            db=db,
            user_id=str(current_user.id),
            timezone=timezone_str,
            local_time=local_time_str,
        )
        response.thread_id = thread_id
        tool_call_names = [tool_call.name for tool_call in response.tool_calls]
        logger.info(
            "Agent chat tool calls: user_id=%s thread_id=%s tool_calls=%s",
            current_user.id,
            thread_id,
            tool_call_names,
        )

        if response.reply.strip():
            try:
                assistant_message = ChatMessage(
                    user_id=current_user.id,
                    thread_id=thread_id,
                    role="assistant",
                    content=response.reply,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(assistant_message)
                db.commit()
            except ProgrammingError:
                db.rollback()
                logger.exception("chat history persistence failed for assistant message; continuing without persistence")

        return response
    except Exception:
        _log_chatbot_api_error(
            api_name="chat",
            request=request,
            user_id=str(current_user.id),
            extra=f"thread_id={payload.thread_id!r}",
        )
        raise


@router.get("/chat/history", response_model=ChatHistoryResponse)
def get_chat_history(
    thread_id: str,
    request: Request,
    limit: int = 50,
    before_created_at: datetime | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatHistoryResponse:
    bounded_limit = max(1, min(limit, 100))
    try:
        query = db.query(ChatMessage).filter(
            and_(
                ChatMessage.user_id == current_user.id,
                ChatMessage.thread_id == thread_id,
            ),
        )
        if before_created_at is not None:
            query = query.filter(ChatMessage.created_at < before_created_at)

        rows = (
            query.order_by(desc(ChatMessage.created_at), desc(ChatMessage.id))
            .limit(bounded_limit + 1)
            .all()
        )
    except ProgrammingError:
        db.rollback()
        logger.exception("chat history query failed; returning empty history")
        return ChatHistoryResponse(items=[], next_before_created_at=None)

    try:
        has_more = len(rows) > bounded_limit
        page_rows = rows[:bounded_limit]
        items = [
            ChatHistoryItem(
                id=row.id,
                thread_id=row.thread_id,
                role=row.role,
                content=row.content,
                created_at=row.created_at,
            )
            for row in reversed(page_rows)
        ]
        next_cursor = page_rows[-1].created_at if has_more and page_rows else None
        return ChatHistoryResponse(items=items, next_before_created_at=next_cursor)
    except Exception:
        _log_chatbot_api_error(
            api_name="chat_history",
            request=request,
            user_id=str(current_user.id),
            extra=f"thread_id={thread_id!r} limit={limit}",
        )
        raise


@router.post("/plant-image/analyze", response_model=PlantImageAnalyzeResponse)
def analyze_plant_image(
    payload: PlantImageAnalyzeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlantImageAnalyzeResponse:
    """Used by the manual 'Add Plant' creation flow (is_manual_creation=True). Not used by the chatbot."""
    user_id = str(current_user.id)
    try:
        preview = payload.image_base64[:200]
        logger.info(
            "Plant image analyze request body: image_base64_len=%d preview=%r",
            len(payload.image_base64),
            preview,
        )
        accept_language = request.headers.get("accept-language", "en")
        language = "vi" if "vi" in accept_language.lower() else "en"

        result = agent.analyze_plant_image(
            payload.image_base64,
            user_id=user_id,
            db=db,
            message=payload.message,
            thread_id=payload.thread_id,
            is_manual_creation=payload.is_manual_creation,
            language=language,
        )
        logger.info("Plant image analyze response body: %s", result.model_dump_json())
        return result
    except Exception:
        _log_chatbot_api_error(
            api_name="plant_image_analyze",
            request=request,
            user_id=user_id,
            extra=f"image_base64_len={len(payload.image_base64)}",
        )
        raise


@router.post("/plant-image/decision", response_model=PlantDecisionResponse)
def apply_plant_decision(
    payload: PlantDecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlantDecisionResponse:
    """Used by the manual 'Add Plant' creation flow. Not used by the chatbot."""
    try:
        accept_language = request.headers.get("accept-language", "en")
        language = "vi" if "vi" in accept_language.lower() else "en"

        decision = agent.apply_plant_decision(
            payload.proposal_id,
            payload.decision,
            payload.edited_data,
            user_id=str(current_user.id),
            db=db,
            thread_id=payload.thread_id,
            language=language,
        )
        if decision.status != "accepted" or decision.data is None:
            return decision

        plant = Plant(
            user_id=current_user.id,
            name=decision.data.plant_name,
            species=decision.data.species,
            image_path=decision.data.image_path or None,
            note=decision.data.note,
            overview=decision.data.overview,
            water=decision.data.water,
            sunlight=decision.data.sunlight,
            fertilizer=decision.data.fertilizer,
            propagating=decision.data.propagating,
            varieties=",".join(decision.data.varieties) if decision.data.varieties else None,
            humidity=decision.data.humidity,
            temperature=decision.data.temperature,
            soil=decision.data.soil,
            running=decision.data.running,
            potting_and_repotting=decision.data.potting_and_repotting,
            pests_and_diseases=decision.data.pests_and_diseases,
            toxicity=decision.data.toxicity,
            propagation=decision.data.propagation,
        )
        db.add(plant)
        db.commit()
        db.refresh(plant)

        return PlantDecisionResponse(
            status=decision.status,
            reply=decision.reply,
            data=decision.data,
            plant_url=str(request.url_for("get_plant", plant_id=plant.id)),
        )
    except Exception:
        _log_chatbot_api_error(
            api_name="plant_image_decision",
            request=request,
            user_id=str(current_user.id),
            extra=f"proposal_id={payload.proposal_id!r} decision={payload.decision!r}",
        )
        raise


@router.post("/chat/stream")
async def chat_with_agent_stream(
    payload: AgentChatRequest,
    request: Request,
    _: User = Depends(get_current_user),
) -> StreamingResponse:
    try:
        accept_language = request.headers.get("accept-language", "en")
        language = "vi" if "vi" in accept_language.lower() else "en"
        timezone_str = request.headers.get("time-zone", "UTC")
        local_time_str = request.headers.get("local-time", None)
        return StreamingResponse(
            agent.chat_stream(
                payload.message,
                language=language,
                timezone=timezone_str,
                local_time=local_time_str,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    except Exception:
        _log_chatbot_api_error(
            api_name="chat_stream",
            request=request,
            extra=f"message_len={len(payload.message)}",
        )
        raise
