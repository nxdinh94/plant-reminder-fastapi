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
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode
    from langgraph.types import Command

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
        self._checkpointer = MemorySaver() if _LANGCHAIN_AVAILABLE else None
        self._graph = self._build_graph() if self._llm_enabled else None
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
                base_url=settings.openrouter_base_url,
                default_headers={
                    "HTTP-Referer": settings.openrouter_site_url or "",
                    "X-OpenRouter-Title": settings.openrouter_site_name or "",
                },
                temperature=0.1,
            )

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
            base_url=settings.openrouter_base_url,
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

    def chat(
        self,
        message: str,
        image_base64: str | None = None,
        thread_id: str | None = None,
        resume_interrupt: bool = False,
    ) -> AgentChatResponse:
        if image_base64:
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
            return AgentChatResponse(
                reply=json.dumps(payload, ensure_ascii=False),
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

    def analyze_plant_image(self, image_base64: str, user_id: str, db: Session) -> PlantImageAnalyzeResponse:
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
                    return PlantImageAnalyzeResponse(
                        status="detected",
                        reply=(
                            "A decision is still pending for your previous image. "
                            "Please accept, reject, or edit that result before sending another image."
                        ),
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
                        return PlantImageAnalyzeResponse(
                            status="detected",
                            reply=(
                                "A decision is still pending for your previous image. "
                                "Please accept, reject, or edit that result before sending another image."
                            ),
                            proposal_id=pending_proposal_id,
                            data=pending_data_with_url,
                            decision_required=True,
                            decision_options=["accept", "reject", "edit"],
                        )

        detected = self._detect_plant(image_base64)
        if detected is None:
            if self._last_plant_image_failure_reason == "provider_error":
                return PlantImageAnalyzeResponse(
                    status="not_detected",
                    reply=(
                        "Image analysis is temporarily unavailable due to an AI service issue. "
                        "Please try again in a moment."
                    ),
                    decision_required=False,
                )
            if self._last_plant_image_failure_reason == "invalid_image":
                return PlantImageAnalyzeResponse(
                    status="not_detected",
                    reply=(
                        "I couldn't read that image format clearly. "
                        "Please send another photo with better lighting and a closer view of the plant."
                    ),
                    decision_required=False,
                )
            return PlantImageAnalyzeResponse(
                status="not_detected",
                reply="I couldn't clearly detect a plant from this image yet. Please try another photo with better lighting and a closer view of the plant.",
                decision_required=False,
            )

        try:
            image_path = _save_base64_image(image_base64, user_id)
        except ValueError:
            return PlantImageAnalyzeResponse(
                status="not_detected",
                reply="Invalid image format. Please try another photo.",
                decision_required=False,
            )

        with self._proposal_lock:
            try:
                proposal_payload = {
                    "plant_name": detected.plant_name,
                    "species": detected.species,
                    "note": detected.note,
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
                )
                self._proposal_store[proposal_id] = detected_with_image
                self._proposal_owner_by_id[proposal_id] = user_id
                self._pending_proposal_by_owner[user_id] = proposal_id

        return PlantImageAnalyzeResponse(
            status="detected",
            reply=(
                "I detected a plant and prepared the information below. "
                "Please review and let me know if I can use this information or if you want to edit it."
            ),
            proposal_id=proposal_id,
            data=PlantDetectionData(
                plant_name=detected.plant_name,
                species=detected.species,
                note=detected.note,
                image_path=_path_to_url(image_path),
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

        # New turn input for same thread_id (multi-turn chat), not a resume.
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
            "First, describe the visible things in this image in one short sentence. "
            "Then decide whether a plant is clearly present. "
            "Return strict JSON only. "
            "If a plant is clearly present, return: "
            "{\"plant_name\":\"...\",\"species\":\"...\",\"note\":\"...\",\"description\":\"...\"}. "
            "If no plant is present or uncertain, return: "
            "{\"not_detected\": true, \"description\":\"...\"}. "
            "Do not include markdown."
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
            return PlantDetectionData(
                plant_name=plant_name,
                species=species,
                note=note,
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
            url=f"{settings.openrouter_base_url}/chat/completions",
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
