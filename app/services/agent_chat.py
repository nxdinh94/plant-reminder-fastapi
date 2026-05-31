from __future__ import annotations

import base64
import json
import uuid
import re
import os
import logging
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from typing import cast
from collections.abc import Sequence
from collections.abc import AsyncIterator
from typing import Any
from threading import Lock
from sqlalchemy.orm import Session
from sqlalchemy.exc import ProgrammingError

try:
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
    from langchain_core.tools import tool
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode
    from langgraph.types import Command
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row

    _LANGCHAIN_AVAILABLE = True
except ModuleNotFoundError:
    _LANGCHAIN_AVAILABLE = False

from app.agent_tools.datetime_tool import datetime_tool, generate_datetime_response, is_datetime_request
from app.agent_tools.small_talk import generate_small_talk_response, small_talk_tool
from app.core.config import settings
from app.models.chat_plant_proposal import ChatPlantProposal
from app.schemas.chat import (
    AgentChatResponse,
    AgentToolCall,
    PlantDecisionResponse,
    PlantDetectionData,
    PlantImageAnalyzeResponse,
)

OPENROUTER_QUICKSTART_CONTEXT = """\
OpenRouter quickstart context:
- OpenRouter exposes a unified OpenAI-compatible API at /api/v1/chat/completions.
- Main integration modes: direct REST API, Client SDKs (@openrouter/sdk, openrouter Python), Agent SDK (@openrouter/agent), or OpenAI SDK with base_url set to OpenRouter.
- Optional attribution headers:
  HTTP-Referer: your site URL
  X-OpenRouter-Title: your app/site name
- Standard auth is Authorization: Bearer <OPENROUTER_API_KEY>.
"""

SYSTEM_PROMPT = f"""\
You are a simple Plant Reminder assistant.
Current capability target: friendly small talk first.
Keep answers concise and clear.
Use small_talk_tool when a message is greeting/chitchat/thanks/bye/how-are-you.
Use datetime_tool for date/time/timezone questions.
Use plant_image_detect_tool when the user provides or asks to analyze base64 plant image data.
If the user asks beyond current capability, clearly say you currently support small talk, datetime, and plant image detection.

Reference document context:
{OPENROUTER_QUICKSTART_CONTEXT}
"""

logger = logging.getLogger(__name__)


def _normalize_base64_payload(payload: str) -> str | None:
    compact = "".join(payload.split())
    if not compact:
        return None
    compact = compact.replace("-", "+").replace("_", "/")
    if re.search(r"[^A-Za-z0-9+/=]", compact):
        return None
    padding = len(compact) % 4
    if padding:
        compact += "=" * (4 - padding)
    try:
        base64.b64decode(compact, validate=False)
    except Exception:
        return None
    return compact


def _save_base64_image(image_base64: str, user_id: str) -> str:
    cleaned = image_base64.strip()
    if cleaned.startswith("data:"):
        comma_idx = cleaned.index(",")
        cleaned = cleaned[comma_idx + 1:]
    normalized_payload = _normalize_base64_payload(cleaned)
    if normalized_payload is None:
        raise ValueError("Invalid base64 image payload")
    filename = f"{user_id}_{uuid.uuid4()}.jpg"
    filepath = str(settings.upload_dir_path / filename)
    os.makedirs(str(settings.upload_dir_path), exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(base64.b64decode(normalized_payload))
    return filepath


def _path_to_url(image_path: str) -> str:
    if not image_path:
        return ""
    if image_path.startswith("http"):
        return image_path
    normalized = image_path.replace("\\", "/")
    upload_dir_str = str(settings.upload_dir_path).replace("\\", "/")
    if normalized.startswith(upload_dir_str):
        relative = normalized[len(upload_dir_str):].lstrip("/")
        return f"/uploads/{relative}"
    if "/uploads/" in normalized:
        idx = normalized.index("/uploads/")
        return normalized[idx:]
    return f"/uploads/{os.path.basename(normalized)}"


class LangGraphChatAgent:
    def __init__(self) -> None:
        self._llm_enabled = bool(settings.openrouter_api_key) and _LANGCHAIN_AVAILABLE
        self._vision_enabled = bool(settings.openrouter_api_key)
        self._llm: Any | None = None
        self._vision_llm: Any | None = None
        self._pool: ConnectionPool | None = None
        self._checkpointer = None
        if _LANGCHAIN_AVAILABLE:
            conn_url = settings.database_url
            if conn_url.startswith("postgresql+psycopg://"):
                conn_url = conn_url.replace("postgresql+psycopg://", "postgresql://", 1)
            elif conn_url.startswith("postgresql+psycopg2://"):
                conn_url = conn_url.replace("postgresql+psycopg2://", "postgresql://", 1)
            try:
                self._pool = ConnectionPool(
                    conninfo=conn_url,
                    max_size=10,
                    kwargs={"autocommit": True, "row_factory": dict_row},
                )
                self._checkpointer = PostgresSaver(self._pool)
                self._checkpointer.setup()
            except Exception:
                logger.exception("Failed to initialize LangGraph PostgresSaver checkpointer; memory will be disabled")
                self._pool = None
                self._checkpointer = None

        # Fallback storage when migration is not yet applied.
        self._proposal_store: dict[str, PlantDetectionData] = {}
        self._proposal_owner_by_id: dict[str, str] = {}
        self._pending_proposal_by_owner: dict[str, str] = {}
        self._last_plant_image_failure_reason: str | None = None
        self._proposal_lock = Lock()
        if self._vision_enabled and _LANGCHAIN_AVAILABLE:
            self._vision_llm = init_chat_model(
                settings.openrouter_model,
                model_provider="openai",
                api_key=settings.openrouter_api_key,
                base_url=settings.PROXY_BASE_URL,
                default_headers={
                    "HTTP-Referer": settings.openrouter_site_url or "",
                    "X-OpenRouter-Title": settings.openrouter_site_name or "",
                },
                temperature=0.1,
            )
        self._graph = self._build_graph() if self._llm_enabled else None

    def close_pool(self) -> None:
        if hasattr(self, "_pool") and self._pool is not None:
            try:
                self._pool.close()
                logger.info("Closed LangGraph Postgres checkpointer connection pool.")
            except Exception:
                logger.exception("Error closing LangGraph Postgres checkpointer connection pool.")

    def _build_graph(self) -> Any:
        @tool("plant_image_detect_tool")
        def plant_image_detect_tool(image_base64: str) -> str:
            """Detect plant information from a base64 image payload and return JSON result."""
            detected = self._detect_plant(image_base64)
            if detected is None:
                return json.dumps({"status": "not_detected"})
            return json.dumps(
                {
                    "status": "detected",
                    "plant_name": detected.plant_name,
                    "species": detected.species,
                    "note": detected.note,
                }
            )

        self._llm = init_chat_model(
            settings.openrouter_model,
            model_provider="openai",
            api_key=settings.openrouter_api_key,
            base_url=settings.PROXY_BASE_URL,
            default_headers={
                "HTTP-Referer": settings.openrouter_site_url or "",
                "X-OpenRouter-Title": settings.openrouter_site_name or "",
            },
            temperature=0.2,
        ).bind_tools([small_talk_tool, datetime_tool, plant_image_detect_tool])

        tool_node = ToolNode([small_talk_tool, datetime_tool, plant_image_detect_tool])

        def assistant_node(state: MessagesState) -> dict[str, list[BaseMessage]]:
            model_response = self._llm.invoke(state["messages"])
            return {"messages": [model_response]}

        def route_after_assistant(state: MessagesState) -> str:
            last_message = state["messages"][-1]
            if isinstance(last_message, AIMessage) and last_message.tool_calls:
                return "tools"
            return "end"

        graph = StateGraph(MessagesState)
        graph.add_node("assistant", assistant_node)
        graph.add_node("tools", tool_node)
        graph.add_edge(START, "assistant")
        graph.add_conditional_edges(
            "assistant",
            route_after_assistant,
            {"tools": "tools", "end": END},
        )
        graph.add_edge("tools", "assistant")
        return graph.compile(checkpointer=self._checkpointer)

    def _classify_intent(self, message: str) -> str:
        """Classify if the user wants to CREATE/add a plant reminder, or just ask a QUESTION."""
        cleaned_msg = message.strip()
        if not cleaned_msg or cleaned_msg.lower() in [
            "sent a plant image",
            "uploaded a plant image",
            "uploaded a plant image.",
            "sent a plant image.",
            "analyze this image",
            "tell me about this plant",
        ]:
            return "CREATE"

        prompt = (
            f"The user uploaded a plant image and sent this message: \"{cleaned_msg}\"\n"
            "Does the user want to create/add/register this plant to their library/reminders list, "
            "or are they just asking a general question/identifying the plant/asking for advice/having small talk?\n"
            "Respond with exactly one word: 'CREATE' (if they want to create/add/register/save a reminder for the plant) "
            "or 'QUESTION' (if they are asking a question, identifying the plant, or chatting without requesting to save/create a reminder)."
        )
        try:
            if not _LANGCHAIN_AVAILABLE:
                return "CREATE"
            llm_to_use = self._vision_llm or self._llm
            if llm_to_use is not None:
                response = llm_to_use.invoke(
                    [
                        SystemMessage(content="You are an intent classification assistant. Respond only with 'CREATE' or 'QUESTION'."),
                        HumanMessage(content=prompt),
                    ]
                )
                raw_classification = self._chunk_text(response.content).strip().upper()
                if "QUESTION" in raw_classification:
                    return "QUESTION"
            return "CREATE"
        except Exception:
            logger.exception("Failed to classify user intent; defaulting to CREATE")
            return "CREATE"

    def _answer_question_with_image(self, message: str, image_base64: str) -> str:
        """Answer the user's question using the plant image."""
        data_url = self._normalize_to_data_url(image_base64)
        if data_url is None:
            return "I couldn't read the image. Please upload a clear photo of the plant."

        prompt = (
            f"The user has uploaded a plant image and asked: \"{message}\"\n"
            "Please analyze the image and answer their question directly, clearly, and concisely."
        )
        try:
            if _LANGCHAIN_AVAILABLE and self._vision_llm is not None:
                response = self._vision_llm.invoke(
                    [
                        SystemMessage(content="You are a helpful plant care assistant. Answer the user's question based on the image."),
                        HumanMessage(
                            content=[
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ]
                        ),
                    ]
                )
                return self._chunk_text(response.content).strip()
        except Exception:
            logger.exception("Failed to invoke self._vision_llm for question")

        # Fallback to model candidates
        for model in self._vision_model_candidates():
            try:
                raw = self._invoke_vision_openrouter_rest(prompt, data_url, model)
                if raw:
                    return raw
            except TypeError:
                raw = self._invoke_vision_openrouter_rest(prompt, data_url)
                if raw:
                    return raw
            except Exception:
                logger.exception("Failed to call vision model %s", model)

        return "I couldn't analyze the plant image to answer your question right now. Please try again."

    def chat(
        self,
        message: str,
        image_base64: str | None = None,
        thread_id: str | None = None,
        resume_interrupt: bool = False,
    ) -> AgentChatResponse:
        if image_base64:
            intent = self._classify_intent(message) if message else "CREATE"
            if intent == "QUESTION":
                reply_content = self._answer_question_with_image(message, image_base64)
                if thread_id and self._graph is not None and _LANGCHAIN_AVAILABLE:
                    config = {"configurable": {"thread_id": thread_id}}
                    try:
                        snapshot = self._graph.get_state(config)
                        has_history = bool(snapshot.values and snapshot.values.get("messages"))
                    except Exception:
                        has_history = False

                    new_messages = []
                    if not has_history:
                        new_messages.append(SystemMessage(content=SYSTEM_PROMPT))
                    
                    user_content = message.strip() if message else ""
                    if not user_content:
                        user_content = "Uploaded a plant image."
                    else:
                        user_content = f"{user_content} [Uploaded a plant image.]"
                    
                    new_messages.append(HumanMessage(content=user_content))
                    new_messages.append(AIMessage(content=reply_content))
                    
                    try:
                        self._graph.update_state(config, {"messages": new_messages})
                    except Exception:
                        logger.exception("Failed to update LangGraph state with image chat message")

                return AgentChatResponse(
                    reply=reply_content,
                    tool_calls=[],
                )

            detected = self._detect_plant(image_base64)
            if detected is None:
                payload = {
                    "is_plant": False,
                    "data": None,
                }
            else:
                payload = {
                    "is_plant": True,
                    "data": {
                        "plant_name": detected.plant_name,
                        "species": detected.species,
                        "note": detected.note,
                    },
                }
            
            reply_content = json.dumps(payload, ensure_ascii=False)

            if thread_id and self._graph is not None:
                config = {"configurable": {"thread_id": thread_id}}
                try:
                    snapshot = self._graph.get_state(config)
                    has_history = bool(snapshot.values and snapshot.values.get("messages"))
                except Exception:
                    has_history = False

                new_messages = []
                if not has_history:
                    new_messages.append(SystemMessage(content=SYSTEM_PROMPT))
                
                user_content = message.strip() if message else ""
                if not user_content:
                    user_content = "Uploaded a plant image."
                else:
                    user_content = f"{user_content} [Uploaded a plant image.]"
                
                new_messages.append(HumanMessage(content=user_content))
                new_messages.append(AIMessage(content=reply_content))
                
                try:
                    self._graph.update_state(config, {"messages": new_messages})
                except Exception:
                    logger.exception("Failed to update LangGraph state with image chat message")

            return AgentChatResponse(
                reply=reply_content,
                tool_calls=[AgentToolCall(name="plant_image_detect_tool")],
            )

        if not self._llm_enabled:
            if is_datetime_request(message):
                return AgentChatResponse(
                    reply=generate_datetime_response(),
                    tool_calls=[AgentToolCall(name="datetime_tool")],
                )
            return AgentChatResponse(
                reply=generate_small_talk_response(message),
                tool_calls=[AgentToolCall(name="small_talk_tool")],
            )

        response_messages = self._invoke_graph(
            message,
            thread_id=thread_id,
            resume_interrupt=resume_interrupt,
        )
        reply = self._extract_final_reply(response_messages)
        tool_calls = self._extract_tool_calls(response_messages)
        return AgentChatResponse(reply=reply, tool_calls=tool_calls)

    def _save_both_histories(
        self,
        db: Session,
        user_id: str,
        thread_id: str,
        user_message: str,
        assistant_sql_message: str,
        assistant_graph_message: str,
    ) -> None:
        from app.models.chat_message import ChatMessage
        from datetime import datetime, timezone, timedelta
        try:
            now = datetime.now(timezone.utc)
            user_msg = ChatMessage(
                user_id=user_id,
                thread_id=thread_id,
                role="user",
                content=user_message,
                created_at=now,
            )
            db.add(user_msg)
            
            assistant_msg = ChatMessage(
                user_id=user_id,
                thread_id=thread_id,
                role="assistant",
                content=assistant_sql_message,
                created_at=now + timedelta(milliseconds=1),
            )
            db.add(assistant_msg)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to save conversation history to SQL database")

        if self._graph is not None and _LANGCHAIN_AVAILABLE and self._checkpointer is not None:
            config = {"configurable": {"thread_id": thread_id}}
            try:
                snapshot = self._graph.get_state(config)
                has_history = bool(snapshot.values and snapshot.values.get("messages"))
            except Exception:
                has_history = False

            new_messages = []
            if not has_history:
                new_messages.append(SystemMessage(content=SYSTEM_PROMPT))
            new_messages.append(HumanMessage(content=user_message))
            new_messages.append(AIMessage(content=assistant_graph_message))

            try:
                self._graph.update_state(config, {"messages": new_messages})
            except Exception:
                logger.exception("Failed to update LangGraph state with conversation messages")

    def analyze_plant_image(
        self,
        image_base64: str,
        user_id: str,
        db: Session,
        message: str | None = None,
        thread_id: str | None = None,
        is_manual_creation: bool = False,
    ) -> PlantImageAnalyzeResponse:
        if message and not is_manual_creation:
            intent = self._classify_intent(message)
            if intent == "QUESTION":
                reply = self._answer_question_with_image(message, image_base64)
                if thread_id:
                    user_text = message.strip()
                    if not user_text:
                        user_text = "Uploaded a plant image."
                    else:
                        user_text = f"{user_text} [Uploaded a plant image.]"
                    self._save_both_histories(db, user_id, thread_id, user_text, reply, reply)
                return PlantImageAnalyzeResponse(
                    status="detected",
                    reply=reply,
                    decision_required=False,
                    data=None,
                    proposal_id=None,
                    decision_options=[],
                )

        if not is_manual_creation:
            with self._proposal_lock:
                try:
                    pending = (
                        db.query(ChatPlantProposal)
                        .filter(
                            ChatPlantProposal.user_id == user_id,
                            ChatPlantProposal.status == "pending",
                        )
                        .one_or_none()
                    )
                    if pending is not None:
                        payload = pending.proposal_payload
                        reply = (
                            "A decision is still pending for your previous image. "
                            "Please accept, reject, or edit that result before sending another image."
                        )
                        if thread_id:
                            user_text = message.strip() if message else ""
                            if not user_text:
                                user_text = "Uploaded a plant image."
                            else:
                                user_text = f"{user_text} [Uploaded a plant image.]"
                            self._save_both_histories(db, user_id, thread_id, user_text, reply, reply)
                        return PlantImageAnalyzeResponse(
                            status="detected",
                            reply=reply,
                            proposal_id=pending.id,
                            data=PlantDetectionData(
                                plant_name=payload.get("plant_name", ""),
                                species=payload.get("species", ""),
                                note=payload.get("note", ""),
                                image_path=_path_to_url(pending.image_path),
                            ),
                            decision_required=True,
                            decision_options=["accept", "reject", "edit"],
                        )
                except ProgrammingError:
                    db.rollback()
                    pending_proposal_id = self._pending_proposal_by_owner.get(user_id)
                    if pending_proposal_id is not None:
                        pending_data = self._proposal_store.get(pending_proposal_id)
                        if pending_data is not None:
                            pending_data_with_url = PlantDetectionData(
                                plant_name=pending_data.plant_name,
                                species=pending_data.species,
                                note=pending_data.note,
                                image_path=_path_to_url(pending_data.image_path),
                            )
                            reply = (
                                "A decision is still pending for your previous image. "
                                "Please accept, reject, or edit that result before sending another image."
                            )
                            if thread_id:
                                user_text = message.strip() if message else ""
                                if not user_text:
                                    user_text = "Uploaded a plant image."
                                else:
                                    user_text = f"{user_text} [Uploaded a plant image.]"
                                self._save_both_histories(db, user_id, thread_id, user_text, reply, reply)
                            return PlantImageAnalyzeResponse(
                                status="detected",
                                reply=reply,
                                proposal_id=pending_proposal_id,
                                data=pending_data_with_url,
                                decision_required=True,
                                decision_options=["accept", "reject", "edit"],
                            )

        detected = self._detect_plant(image_base64)
        if detected is None:
            if self._last_plant_image_failure_reason == "provider_error":
                reply = (
                    "Image analysis is temporarily unavailable due to an AI service issue. "
                    "Please try again in a moment."
                )
            elif self._last_plant_image_failure_reason == "invalid_image":
                reply = (
                    "I couldn't read that image format clearly. "
                    "Please send another photo with better lighting and a closer view of the plant."
                )
            else:
                reply = "I couldn't clearly detect a plant from this image yet. Please try another photo with better lighting and a closer view of the plant."

            if thread_id:
                user_text = message.strip() if message else ""
                if not user_text:
                    user_text = "Uploaded a plant image."
                else:
                    user_text = f"{user_text} [Uploaded a plant image.]"
                self._save_both_histories(db, user_id, thread_id, user_text, reply, reply)

            return PlantImageAnalyzeResponse(
                status="not_detected",
                reply=reply,
                decision_required=False,
            )

        try:
            image_path = _save_base64_image(image_base64, user_id)
        except ValueError:
            reply = "Invalid image format. Please try another photo."
            if thread_id:
                user_text = message.strip() if message else ""
                if not user_text:
                    user_text = "Uploaded a plant image."
                else:
                    user_text = f"{user_text} [Uploaded a plant image.]"
                self._save_both_histories(db, user_id, thread_id, user_text, reply, reply)
            return PlantImageAnalyzeResponse(
                status="not_detected",
                reply=reply,
                decision_required=False,
            )

        if is_manual_creation:
            reply = "I detected a plant and prepared the information below."
            return PlantImageAnalyzeResponse(
                status="detected",
                reply=reply,
                proposal_id=None,
                data=PlantDetectionData(
                    plant_name=detected.plant_name,
                    species=detected.species,
                    note=detected.note,
                    image_path=_path_to_url(image_path),
                    overview=detected.overview,
                    water=detected.water,
                    sunlight=detected.sunlight,
                    fertilizer=detected.fertilizer,
                    propagating=detected.propagating,
                    varieties=detected.varieties,
                    humidity=detected.humidity,
                    temperature=detected.temperature,
                    soil=detected.soil,
                    running=detected.running,
                    potting_and_repotting=detected.potting_and_repotting,
                    pests_and_diseases=detected.pests_and_diseases,
                    toxicity=detected.toxicity,
                    propagation=detected.propagation,
                ),
                decision_required=False,
                decision_options=[],
            )

        with self._proposal_lock:
            try:
                proposal_payload = {
                    "plant_name": detected.plant_name,
                    "species": detected.species,
                    "note": detected.note,
                    "overview": detected.overview,
                    "water": detected.water,
                    "sunlight": detected.sunlight,
                    "fertilizer": detected.fertilizer,
                    "propagating": detected.propagating,
                    "varieties": detected.varieties,
                    "humidity": detected.humidity,
                    "temperature": detected.temperature,
                    "soil": detected.soil,
                    "running": detected.running,
                    "potting_and_repotting": detected.potting_and_repotting,
                    "pests_and_diseases": detected.pests_and_diseases,
                    "toxicity": detected.toxicity,
                    "propagation": detected.propagation,
                }
                proposal = ChatPlantProposal(
                    user_id=user_id,
                    chat_message_id=None,
                    status="pending",
                    proposal_payload=proposal_payload,
                    image_path=image_path,
                    revision=1,
                )
                db.add(proposal)
                db.commit()
                db.refresh(proposal)
                proposal_id = proposal.id
            except ProgrammingError:
                db.rollback()
                proposal_id = str(uuid.uuid4())
                detected_with_image = PlantDetectionData(
                    plant_name=detected.plant_name,
                    species=detected.species,
                    note=detected.note,
                    image_path=image_path,
                    overview=detected.overview,
                    water=detected.water,
                    sunlight=detected.sunlight,
                    fertilizer=detected.fertilizer,
                    propagating=detected.propagating,
                    varieties=detected.varieties,
                    humidity=detected.humidity,
                    temperature=detected.temperature,
                    soil=detected.soil,
                    running=detected.running,
                    potting_and_repotting=detected.potting_and_repotting,
                    pests_and_diseases=detected.pests_and_diseases,
                    toxicity=detected.toxicity,
                    propagation=detected.propagation,
                )
                self._proposal_store[proposal_id] = detected_with_image
                self._proposal_owner_by_id[proposal_id] = user_id
                self._pending_proposal_by_owner[user_id] = proposal_id

        reply = (
            "I detected a plant and prepared the information below. "
            "Please review and let me know if I can use this information or if you want to edit it."
        )

        if thread_id:
            user_text = message.strip() if message else ""
            if not user_text:
                user_text = "Uploaded a plant image."
            else:
                user_text = f"{user_text} [Uploaded a plant image.]"
            
            desc_parts = []
            desc_parts.append(f"I detected a plant: {detected.plant_name} ({detected.species}).")
            if detected.note:
                desc_parts.append(f"Care Note: {detected.note}.")
            if detected.overview:
                desc_parts.append(f"Overview: {detected.overview}")
            if detected.water:
                desc_parts.append(f"Watering: {detected.water}")
            if detected.sunlight:
                desc_parts.append(f"Sunlight: {detected.sunlight}")
            desc_parts.append(reply)
            
            assistant_graph_text = " ".join(desc_parts)
            self._save_both_histories(db, user_id, thread_id, user_text, reply, assistant_graph_text)

        return PlantImageAnalyzeResponse(
            status="detected",
            reply=reply,
            proposal_id=proposal_id,
            data=PlantDetectionData(
                plant_name=detected.plant_name,
                species=detected.species,
                note=detected.note,
                image_path=_path_to_url(image_path),
                overview=detected.overview,
                water=detected.water,
                sunlight=detected.sunlight,
                fertilizer=detected.fertilizer,
                propagating=detected.propagating,
                varieties=detected.varieties,
                humidity=detected.humidity,
                temperature=detected.temperature,
                soil=detected.soil,
                running=detected.running,
                potting_and_repotting=detected.potting_and_repotting,
                pests_and_diseases=detected.pests_and_diseases,
                toxicity=detected.toxicity,
                propagation=detected.propagation,
            ),
            decision_required=True,
            decision_options=["accept", "reject", "edit"],
        )

    def apply_plant_decision(
        self,
        proposal_id: str,
        decision: str,
        edited_data: PlantDetectionData | None,
        user_id: str,
        db: Session,
        thread_id: str | None = None,
    ) -> PlantDecisionResponse:
        plant_name = "Unknown Plant"
        species = "Unknown Species"
        with self._proposal_lock:
            try:
                current_db = (
                    db.query(ChatPlantProposal)
                    .filter(
                        ChatPlantProposal.id == proposal_id,
                        ChatPlantProposal.user_id == user_id,
                        ChatPlantProposal.status == "pending",
                    )
                    .one_or_none()
                )
                if current_db is not None:
                    plant_name = current_db.proposal_payload.get("plant_name", "Unknown Plant")
                    species = current_db.proposal_payload.get("species", "Unknown Species")
            except Exception:
                pass
            if plant_name == "Unknown Plant":
                current_mem = self._proposal_store.get(proposal_id)
                if current_mem is not None:
                    plant_name = current_mem.plant_name
                    species = current_mem.species

        response = self._apply_plant_decision_internal(
            proposal_id=proposal_id,
            decision=decision,
            edited_data=edited_data,
            user_id=user_id,
            db=db,
        )

        if thread_id and response.status != "invalid":
            if decision == "accept":
                user_text = f"I accept the proposal to add the plant: {plant_name} ({species})."
            elif decision == "reject":
                user_text = f"I reject the proposal to add the plant: {plant_name} ({species})."
            elif decision == "edit":
                user_text = f"I edited the proposal for the plant: {plant_name} ({species})."
                if edited_data:
                    user_text += f" New details: Name={edited_data.plant_name}, Species={edited_data.species}, Note={edited_data.note}."
            else:
                user_text = f"Decision made: {decision} on plant proposal."
            
            self._save_both_histories(db, user_id, thread_id, user_text, response.reply, response.reply)

        return response

    def _apply_plant_decision_internal(
        self,
        proposal_id: str,
        decision: str,
        edited_data: PlantDetectionData | None,
        user_id: str,
        db: Session,
    ) -> PlantDecisionResponse:
        with self._proposal_lock:
            try:
                current = (
                    db.query(ChatPlantProposal)
                    .filter(
                        ChatPlantProposal.id == proposal_id,
                        ChatPlantProposal.user_id == user_id,
                        ChatPlantProposal.status == "pending",
                    )
                    .one_or_none()
                )
                if current is None:
                    return PlantDecisionResponse(
                        status="invalid",
                        reply="This decision request is no longer valid. Please send the image again.",
                    )
                payload = current.proposal_payload
                if decision == "accept":
                    accepted_data = PlantDetectionData(
                        plant_name=payload.get("plant_name", ""),
                        species=payload.get("species", ""),
                        note=payload.get("note", ""),
                        image_path=_path_to_url(current.image_path),
                        overview=payload.get("overview"),
                        water=payload.get("water"),
                        sunlight=payload.get("sunlight"),
                        fertilizer=payload.get("fertilizer"),
                        propagating=payload.get("propagating"),
                        varieties=payload.get("varieties", []),
                        humidity=payload.get("humidity"),
                        temperature=payload.get("temperature"),
                        soil=payload.get("soil"),
                        running=payload.get("running"),
                        potting_and_repotting=payload.get("potting_and_repotting"),
                        pests_and_diseases=payload.get("pests_and_diseases"),
                        toxicity=payload.get("toxicity"),
                        propagation=payload.get("propagation"),
                    )
                    current.status = "approved"
                    db.commit()
                    return PlantDecisionResponse(
                        status="accepted",
                        reply="Accepted. I will use this plant information.",
                        data=accepted_data,
                    )

                if decision == "reject":
                    current.status = "rejected"
                    db.commit()
                    return PlantDecisionResponse(
                        status="rejected",
                        reply="Understood. I discarded this detected result.",
                    )

                if decision == "edit":
                    if edited_data is None:
                        return PlantDecisionResponse(
                            status="invalid",
                            reply="Please include edited_data when decision is edit.",
                        )
                    current.proposal_payload = {
                        **payload,
                        "plant_name": edited_data.plant_name,
                        "species": edited_data.species,
                        "note": edited_data.note,
                        "overview": edited_data.overview,
                        "water": edited_data.water,
                        "sunlight": edited_data.sunlight,
                        "fertilizer": edited_data.fertilizer,
                        "propagating": edited_data.propagating,
                        "varieties": edited_data.varieties,
                        "humidity": edited_data.humidity,
                        "temperature": edited_data.temperature,
                        "soil": edited_data.soil,
                        "running": edited_data.running,
                        "potting_and_repotting": edited_data.potting_and_repotting,
                        "pests_and_diseases": edited_data.pests_and_diseases,
                        "toxicity": edited_data.toxicity,
                        "propagation": edited_data.propagation,
                    }
                    current.revision = (current.revision or 1) + 1
                    db.commit()
                    return PlantDecisionResponse(
                        status="edited",
                        reply="Updated. I will use your edited plant information.",
                        data=edited_data,
                    )
            except ProgrammingError:
                db.rollback()
                current = self._proposal_store.get(proposal_id)
                owner_id = self._proposal_owner_by_id.get(proposal_id)
                if current is None or owner_id != user_id:
                    return PlantDecisionResponse(
                        status="invalid",
                        reply="This decision request is no longer valid. Please send the image again.",
                    )
                if decision == "accept":
                    accepted_data = self._proposal_store.pop(proposal_id)
                    self._proposal_owner_by_id.pop(proposal_id, None)
                    self._pending_proposal_by_owner.pop(user_id, None)
                    accepted_data_with_url = PlantDetectionData(
                        plant_name=accepted_data.plant_name,
                        species=accepted_data.species,
                        note=accepted_data.note,
                        image_path=_path_to_url(accepted_data.image_path),
                        overview=accepted_data.overview,
                        water=accepted_data.water,
                        sunlight=accepted_data.sunlight,
                        fertilizer=accepted_data.fertilizer,
                        propagating=accepted_data.propagating,
                        varieties=accepted_data.varieties,
                        humidity=accepted_data.humidity,
                        temperature=accepted_data.temperature,
                        soil=accepted_data.soil,
                        running=accepted_data.running,
                        potting_and_repotting=accepted_data.potting_and_repotting,
                        pests_and_diseases=accepted_data.pests_and_diseases,
                        toxicity=accepted_data.toxicity,
                        propagation=accepted_data.propagation,
                    )
                    return PlantDecisionResponse(
                        status="accepted",
                        reply="Accepted. I will use this plant information.",
                        data=accepted_data_with_url,
                    )
                if decision == "reject":
                    self._proposal_store.pop(proposal_id, None)
                    self._proposal_owner_by_id.pop(proposal_id, None)
                    self._pending_proposal_by_owner.pop(user_id, None)
                    return PlantDecisionResponse(
                        status="rejected",
                        reply="Understood. I discarded this detected result.",
                    )
                if decision == "edit":
                    if edited_data is None:
                        return PlantDecisionResponse(
                            status="invalid",
                            reply="Please include edited_data when decision is edit.",
                        )
                    self._proposal_store.pop(proposal_id, None)
                    self._proposal_owner_by_id.pop(proposal_id, None)
                    self._pending_proposal_by_owner.pop(user_id, None)
                    return PlantDecisionResponse(
                        status="edited",
                        reply="Updated. I will use your edited plant information.",
                        data=edited_data,
                    )

        return PlantDecisionResponse(
            status="invalid",
            reply="Unsupported decision.",
        )

    async def chat_stream(self, message: str) -> AsyncIterator[str]:
        if not self._llm_enabled or self._llm is None:
            fallback_reply = generate_small_talk_response(message)
            yield self._sse("chunk", fallback_reply)
            yield self._sse("done", json.dumps({"reply": fallback_reply}))
            return

        full_reply = ""
        async for chunk in self._llm.astream(
            [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=message),
            ]
        ):
            content = self._chunk_text(chunk.content)
            if not content:
                continue
            full_reply += content
            yield self._sse("chunk", content)

        yield self._sse("done", json.dumps({"reply": full_reply.strip()}))

    def _invoke_graph(
        self,
        message: str,
        thread_id: str | None = None,
        resume_interrupt: bool = False,
    ) -> Sequence[BaseMessage]:
        if self._graph is None:
            return [AIMessage(content=generate_small_talk_response(message))]

        state: dict[str, Any]
        if thread_id is None:
            state = self._graph.invoke(
                {
                    "messages": [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=message),
                    ]
                }
            )
            return cast(Sequence[BaseMessage], state["messages"])

        config = {"configurable": {"thread_id": thread_id}}
        has_pending_interrupt = self._thread_has_pending_interrupt(config)

        # Only resume when both conditions are true:
        # 1) caller explicitly requests resume
        # 2) this thread currently has a pending interrupt
        if resume_interrupt and has_pending_interrupt:
            state = self._graph.invoke(Command(resume=message), config=config)
            return cast(Sequence[BaseMessage], state["messages"])

        # Check if the thread already has messages in memory
        try:
            snapshot = self._graph.get_state(config)
            has_history = bool(snapshot.values and snapshot.values.get("messages"))
        except Exception:
            has_history = False

        # New turn input for same thread_id (multi-turn chat), not a resume.
        if not has_history:
            # First message on this thread: prepend SystemMessage instructions
            state = self._graph.invoke(
                {
                    "messages": [
                        SystemMessage(content=SYSTEM_PROMPT),
                        HumanMessage(content=message),
                    ]
                },
                config=config,
            )
        else:
            # Subsequent messages: append only the human message
            state = self._graph.invoke(
                {
                    "messages": [
                        HumanMessage(content=message),
                    ]
                },
                config=config,
            )
        return state["messages"]

    def _thread_has_pending_interrupt(self, config: dict[str, dict[str, str]]) -> bool:
        if self._graph is None:
            return False
        try:
            snapshot = self._graph.get_state(config)
        except Exception:
            return False
        interrupts = getattr(snapshot, "interrupts", None)
        return bool(interrupts)

    @staticmethod
    def _extract_final_reply(messages: Sequence[BaseMessage]) -> str:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
                return msg.content.strip()
        return "I can handle small talk and datetime questions for now."

    @staticmethod
    def _extract_tool_calls(messages: Sequence[BaseMessage]) -> list[AgentToolCall]:
        tool_calls: list[AgentToolCall] = []
        seen: set[str] = set()
        for msg in messages:
            if not isinstance(msg, AIMessage):
                continue
            for tool_call in msg.tool_calls:
                name = tool_call.get("name")
                if name and name not in seen:
                    seen.add(name)
                    tool_calls.append(AgentToolCall(name=name))
        return tool_calls

    @staticmethod
    def _chunk_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
        return ""

    @staticmethod
    def _sse(event: str, data: str) -> str:
        return f"event: {event}\ndata: {data}\n\n"

    def _detect_plant(self, image_base64: str) -> PlantDetectionData | None:
        self._last_plant_image_failure_reason = None
        if not self._vision_enabled:
            logger.warning(
                "Plant image analyze skipped: vision disabled (has_api_key=%s)",
                bool(settings.openrouter_api_key),
            )
            self._last_plant_image_failure_reason = "provider_error"
            return None

        data_url = self._normalize_to_data_url(image_base64)
        if data_url is None:
            logger.warning("Plant image analyze failed: invalid base64 payload after normalization")
            self._last_plant_image_failure_reason = "invalid_image"
            return None

        prompt = (
            "Analyze this plant image and return strict JSON only. "
            "If a plant is clearly present, return a JSON object with ALL of these keys: "
            "{\"plant_name\":\"...\",\"species\":\"...\",\"note\":\"...\","
            "\"overview\":\"brief description of the plant (e.g. Weeping fig is an evergreen tree or large shrub, typically reaching heights of 10-30m. It has a dense and weeping crown...)\","
            "\"water\":\"detailed watering guidance with frequency and soil dryness indicators (e.g. Water when top 2-3cm of soil feels dry, typically every 5-7 days in growing season)\","
            "\"sunlight\":\"light placement guidance - where to put and where to avoid (e.g. Bright indirect light, avoid direct afternoon sun which can scorch leaves)\","
            "\"fertilizer\":\"how and when to fertilize (e.g. Apply balanced liquid fertilizer every 2-4 weeks during spring and summer, reduce in fall and winter)\","
            "\"propagating\":\"short practical propagation method summary (e.g. Stem cuttings in water or moist soil, best in spring)\","
            "\"varieties\":[\"related variety 1\",\"related variety 2\"],"
            "\"humidity\":\"useful humidity information with range (e.g. Prefers 50-70% humidity, mist leaves regularly or use a pebble tray)\","
            "\"temperature\":\"suitable temperature range for growth (e.g. 18-27°C / 65-80°F, avoid cold drafts and temperatures below 15°C)\","
            "\"soil\":\"soil type, pH range, and drainage requirements (e.g. Well-draining potting mix with pH 6.0-6.5, add perlite for drainage)\","
            "\"running\":\"growth rate and habit information (e.g. Moderate to fast grower, can reach 1-2m indoors, weeping habit)\","
            "\"potting_and_repotting\":\"when and how to repot (e.g. Repot every 1-2 years in spring, choose pot 2-5cm larger, refresh soil)\","
            "\"pests_and_diseases\":\"common pests and diseases to watch for (e.g. Watch for spider mites, scale, and mealybugs; treat with neem oil)\","
            "\"toxicity\":\"whether toxic to pets or humans (e.g. Toxic to cats and dogs if ingested, causes drooling and vomiting)\","
            "\"propagation\":\"detailed step-by-step propagation guidance (e.g. 1) Take a 10-15cm stem cutting with 2-3 nodes... 2) Remove lower leaves... 3) Place in water or moist soil... 4) Keep warm and bright until roots develop in 2-4 weeks...)"
            "}. "
            "If no plant is present or uncertain, return: "
            "{\"not_detected\": true, \"description\":\"...\"}. "
            "Do not include markdown. Use cautious language like 'typically' or 'commonly' when uncertain."
        )
        raw = ""
        if self._vision_llm is not None:
            try:
                response = self._vision_llm.invoke(
                    [
                        SystemMessage(content="You are a plant image analysis assistant."),
                        HumanMessage(
                            content=[
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ]
                        ),
                    ]
                )
                raw = self._chunk_text(response.content).strip()
            except Exception:
                logger.exception("Plant image analyze failed: langchain model invocation error")
                # Fallback to direct REST calls with candidate vision models.
                raw = ""
        for model in self._vision_model_candidates():
            if raw:
                break
            try:
                raw = self._invoke_vision_openrouter_rest(prompt, data_url, model)
            except TypeError:
                # Backward-compatible path for tests that monkeypatch a 2-arg callable.
                raw = self._invoke_vision_openrouter_rest(prompt, data_url)
        if not raw:
            logger.warning("Plant image analyze failed: empty model response")
            self._last_plant_image_failure_reason = "provider_error"
            return None
        payload = self._parse_vision_payload(raw)
        if payload is None:
            logger.warning("Plant image analyze non-JSON response; trying text fallback snippet=%r", raw[:300])
            fallback = self._detect_plant_from_text(raw)
            if fallback is not None:
                return fallback
            self._last_plant_image_failure_reason = "provider_error"
            return None

        if self._is_not_detected_payload(payload):
            logger.info("Plant image analyze result: model returned not_detected")
            return None
        try:
            plant_name = self._extract_text_field(
                payload,
                "plant_name",
                "name",
                "common_name",
                "title",
            )
            species = self._extract_text_field(
                payload,
                "species",
                "scientific_name",
                "botanical_name",
            )
            note = self._extract_text_field(
                payload,
                "note",
                "short_care_guide",
                "care_guide",
                "description",
            )
            if not plant_name:
                logger.warning("Plant image analyze failed: JSON missing expected keys payload=%r", payload)
                return None
            if not species:
                species = "Unknown"
            if not note:
                note = "General care: bright indirect light, water when topsoil is dry, and avoid overwatering."

            overview = payload.get("overview")
            water = payload.get("water")
            sunlight = payload.get("sunlight")
            fertilizer = payload.get("fertilizer")
            propagating = payload.get("propagating")
            varieties = payload.get("varieties", [])
            if isinstance(varieties, str):
                varieties = [v.strip() for v in varieties.split(",") if v.strip()]
            elif not isinstance(varieties, list):
                varieties = []
            humidity = payload.get("humidity")
            temperature = payload.get("temperature")
            soil = payload.get("soil")
            running = payload.get("running")
            potting_and_repotting = payload.get("potting_and_repotting")
            pests_and_diseases = payload.get("pests_and_diseases")
            toxicity = payload.get("toxicity")
            propagation = payload.get("propagation")

            return PlantDetectionData(
                plant_name=plant_name,
                species=species,
                note=note,
                overview=overview if isinstance(overview, str) else None,
                water=water if isinstance(water, str) else None,
                sunlight=sunlight if isinstance(sunlight, str) else None,
                fertilizer=fertilizer if isinstance(fertilizer, str) else None,
                propagating=propagating if isinstance(propagating, str) else None,
                varieties=varieties,
                humidity=humidity if isinstance(humidity, str) else None,
                temperature=temperature if isinstance(temperature, str) else None,
                soil=soil if isinstance(soil, str) else None,
                running=running if isinstance(running, str) else None,
                potting_and_repotting=potting_and_repotting if isinstance(potting_and_repotting, str) else None,
                pests_and_diseases=pests_and_diseases if isinstance(pests_and_diseases, str) else None,
                toxicity=toxicity if isinstance(toxicity, str) else None,
                propagation=propagation if isinstance(propagation, str) else None,
            )
        except Exception:
            logger.warning("Plant image analyze failed: JSON missing expected keys payload=%r", payload)
            return None

    @staticmethod
    def _normalize_to_data_url(image_base64: str) -> str | None:
        cleaned = image_base64.strip()
        if not cleaned:
            return None

        data_url_match = re.match(r"^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$", cleaned, re.DOTALL)
        if data_url_match:
            mime = data_url_match.group(1)
            payload = data_url_match.group(2)
            normalized_payload = LangGraphChatAgent._normalize_base64_payload(payload)
            if normalized_payload is None:
                return None
            return f"data:{mime};base64,{normalized_payload}"

        normalized_payload = LangGraphChatAgent._normalize_base64_payload(cleaned)
        if normalized_payload is None:
            return None
        return f"data:image/jpeg;base64,{normalized_payload}"

    @staticmethod
    def _normalize_base64_payload(payload: str) -> str | None:
        compact = "".join(payload.split())
        if not compact:
            return None

        compact = compact.replace("-", "+").replace("_", "/")
        if re.search(r"[^A-Za-z0-9+/=]", compact):
            return None
        padding = len(compact) % 4
        if padding:
            compact += "=" * (4 - padding)
        try:
            base64.b64decode(compact, validate=False)
        except Exception:
            return None
        return compact

    @staticmethod
    def _extract_json_object(raw: str) -> str:
        if not raw:
            return raw
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return raw[start : end + 1]
        return raw

    @staticmethod
    def _parse_vision_payload(raw: str) -> dict[str, Any] | None:
        candidates: list[str] = []

        # 1) raw as-is
        candidates.append(raw)

        # 2) fenced JSON blocks
        for block in re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw, flags=re.IGNORECASE):
            candidates.append(block)

        # 3) broad slice from first "{" to last "}"
        candidates.append(LangGraphChatAgent._extract_json_object(raw))

        for candidate in candidates:
            text = candidate.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return cast(dict[str, Any], payload)
        return None

    @staticmethod
    def _extract_text_field(payload: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned:
                    return cleaned
        return ""

    @staticmethod
    def _is_not_detected_payload(payload: dict[str, Any]) -> bool:
        marker = payload.get("not_detected")
        if isinstance(marker, bool):
            return marker
        if isinstance(marker, str):
            return marker.strip().lower() in {"true", "yes", "1"}
        # Some models use a status field instead of not_detected boolean.
        status = payload.get("status")
        if isinstance(status, str):
            normalized = status.strip().lower()
            return normalized in {"not_detected", "not detected", "undetected", "none"}
        return False

    @staticmethod
    def _detect_plant_from_text(raw: str) -> PlantDetectionData | None:
        text = raw.lower()
        plant_keywords = [
            "plant",
            "leaf",
            "leaves",
            "flower",
            "tree",
            "succulent",
            "herb",
            "grass",
            "fern",
            "cactus",
            "pot",
            "foliage",
        ]
        if not any(k in text for k in plant_keywords):
            return None

        # Best-effort fallback when model does not follow JSON contract.
        return PlantDetectionData(
            plant_name="Unknown plant (from image description)",
            species="Unknown",
            note=(
                "Place in bright indirect light, water when topsoil is dry, "
                "and avoid overwatering until species is confirmed."
            ),
        )

    def _vision_model_candidates(self) -> list[str]:
        configured = [model for model in settings.openrouter_vision_models if model]
        base = [settings.openrouter_model] + configured + [
            "google/gemini-2.5-flash",
            "openai/gpt-4o-mini",
        ]
        deduped: list[str] = []
        for model in base:
            normalized = model.strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    def _invoke_vision_openrouter_rest(self, prompt: str, data_url: str, model: str | None = None) -> str:
        selected_model = (model or settings.openrouter_model).strip()
        payload = {
            "model": selected_model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a plant image analysis assistant.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            "temperature": 0.1,
        }
        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url
        if settings.openrouter_site_name:
            headers["X-OpenRouter-Title"] = settings.openrouter_site_name

        req = urllib_request.Request(
            url=f"{settings.PROXY_BASE_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8")
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:400]
            except Exception:
                detail = ""
            logger.warning(
                "Plant image analyze failed: openrouter HTTP error model=%s status=%s detail=%r",
                selected_model,
                exc.code,
                detail,
            )
            return ""
        except URLError:
            logger.exception("Plant image analyze failed: openrouter URL error model=%s", selected_model)
            return ""
        except Exception:
            logger.exception("Plant image analyze failed: openrouter request error model=%s", selected_model)
            return ""

        try:
            parsed = json.loads(body)
            return (
                parsed.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
        except Exception:
            logger.warning("Plant image analyze failed: invalid OpenRouter response snippet=%r", body[:300])
            return ""


agent = LangGraphChatAgent()
