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
    from langgraph.prebuilt import ToolNode, InjectedState
    from typing import Annotated
    from langgraph.types import Command
    from psycopg_pool import ConnectionPool
    from psycopg.rows import dict_row

    _LANGCHAIN_AVAILABLE = True
except ModuleNotFoundError:
    _LANGCHAIN_AVAILABLE = False

from app.agent_tools.small_talk import generate_small_talk_response, small_talk_tool
from app.agent_tools.user_insights import (
    _last_interacted_schedule_id,
    get_user_journal_insight_payload,
    get_user_plant_insight_payload,
    manage_plant_schedules_tool,
    reset_user_insight_context,
    set_user_insight_context,
    users_journal_insight_tool,
    users_plant_insight_tool,
)
from app.core.config import settings
from app.models.chat_plant_proposal import ChatPlantProposal
from app.services.media_storage import (
    MediaStorageValidationError,
    store_image_bytes_sync,
)
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
You are a friendly Plant Reminder assistant.
Keep answers concise and clear.
Use small_talk_tool when a message is greeting/chitchat/thanks/bye/how-are-you.
Use manage_plant_schedules_tool when the user wants to create, read/view, update/edit, or delete/remove a scheduled task or care reminder (such as watering, fertilizing, repotting, pruning, misting) for their plant.
Use users_plant_insight_tool only for general saved plant/library/profile/care-field/schedule/task-completion questions, including relative dates such as today, yesterday, or tomorrow when the user asks about plant tasks.
Use users_journal_insight_tool only for journal, note, log, history, progress, symptoms-over-time, or what-the-user-recorded questions.
If wording is ambiguous like "my plant" and does not mention journal/history/notes/logs, choose users_plant_insight_tool only.
Do not call both plant and journal insight tools unless the user explicitly asks for both saved plant profile details and journal history.
If the user asks beyond current capability, clearly say you currently support small talk, plant image analysis, saved plant insight, journal insight, and managing plant reminders/schedules.

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
    content_type = "image/jpeg"
    extension = ".jpg"
    data_url_match = re.match(r"^data:(image\/[a-zA-Z0-9.+-]+);base64,(.+)$", cleaned, re.DOTALL)
    if data_url_match:
        content_type = data_url_match.group(1).lower()
        extension = _extension_for_image_content_type(content_type)
        cleaned = data_url_match.group(2)
    elif cleaned.startswith("data:"):
        raise ValueError("Invalid base64 image payload")

    normalized_payload = _normalize_base64_payload(cleaned)
    if normalized_payload is None:
        raise ValueError("Invalid base64 image payload")
    try:
        stored = store_image_bytes_sync(
            base64.b64decode(normalized_payload),
            user_id=user_id,
            original_filename=f"image{extension}",
            supplied_content_type=content_type,
        )
    except MediaStorageValidationError as exc:
        raise ValueError(exc.detail) from exc
    return stored.path


def _extension_for_image_content_type(content_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }.get(content_type, ".jpg")


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
        self._last_uploaded_image: dict[str, str] = {}
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

    def _get_system_prompt(self, language: str = "vi", timezone: str = "UTC", local_time: str | None = None) -> str:
        from datetime import datetime, timedelta, timezone as datetime_timezone
        import zoneinfo

        today_str = None
        current_time_str = None

        if local_time:
            try:
                dt = datetime.fromisoformat(local_time.replace(" ", "T"))
                today_str = dt.date().isoformat()
                current_time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

        if not today_str and timezone:
            try:
                tz = zoneinfo.ZoneInfo(timezone)
                dt = datetime.now(tz)
                today_str = dt.date().isoformat()
                current_time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                offset_match = re.fullmatch(
                    r"(?:(?:GMT|UTC)\s*)?([+-])(\d{1,2})(?::?(\d{2}))?",
                    timezone.strip(),
                    re.IGNORECASE,
                )
                if offset_match:
                    sign, hours_raw, minutes_raw = offset_match.groups()
                    hours = int(hours_raw)
                    minutes = int(minutes_raw or "0")
                    if hours <= 23 and minutes <= 59:
                        delta = timedelta(hours=hours, minutes=minutes)
                        if sign == "-":
                            delta = -delta
                        dt = datetime.now(datetime_timezone(delta))
                        today_str = dt.date().isoformat()
                        current_time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        if not today_str:
            from datetime import date
            today_str = date.today().isoformat()
            current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            dt = datetime.fromisoformat(today_str)
            day_of_week = dt.strftime("%A")
        except Exception:
            day_of_week = "unknown"

        lang_instruction = "Response MUST be in Vietnamese language." if language == "vi" else "Response MUST be in English language."
        date_context = (
            f"The user's current local date is {today_str} ({day_of_week}) "
            f"and current local time is {current_time_str}. Timezone: {timezone}. "
            "This current date/time context supersedes any older date/time context in prior "
            "thread messages; use it for all relative dates and schedule creation."
        )
        return f"{SYSTEM_PROMPT}\n\n{date_context}\n{lang_instruction}"

    def close_pool(self) -> None:
        if hasattr(self, "_pool") and self._pool is not None:
            try:
                self._pool.close()
                logger.info("Closed LangGraph Postgres checkpointer connection pool.")
            except Exception:
                logger.exception("Error closing LangGraph Postgres checkpointer connection pool.")

    def _build_graph(self) -> Any:
        insight_tools = [
            small_talk_tool,
            users_plant_insight_tool,
            users_journal_insight_tool,
            manage_plant_schedules_tool,
        ]

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
        ).bind_tools(insight_tools)

        tool_node = ToolNode(insight_tools)

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
        """Classify if the user wants to SAVE/add a plant or just ask a QUESTION about it."""
        cleaned_msg = message.strip()
        if not cleaned_msg:
            # Empty message with image → ask clarification (handled by caller)
            return "CLARIFY"

        prompt = (
            f"The user uploaded a plant image and sent this message: \"{cleaned_msg}\"\n"
            "Does the user want to save/add/register this plant to their library/reminders list, "
            "or are they just asking a general question/identifying the plant/asking for advice/having small talk?\n"
            "Respond with exactly one word: 'SAVE' (if they want to save/add/register a reminder for the plant) "
            "or 'QUESTION' (if they are asking a question, identifying the plant, or chatting without requesting to save/create a reminder)."
        )
        try:
            if not _LANGCHAIN_AVAILABLE:
                return "SAVE"
            llm_to_use = self._vision_llm or self._llm
            if llm_to_use is not None:
                response = llm_to_use.invoke(
                    [
                        SystemMessage(content="You are an intent classification assistant. Respond only with 'SAVE' or 'QUESTION'."),
                        HumanMessage(content=prompt),
                    ]
                )
                raw_classification = self._chunk_text(response.content).strip().upper()
                if "QUESTION" in raw_classification:
                    return "QUESTION"
            return "SAVE"
        except Exception:
            logger.exception("Failed to classify user intent; defaulting to SAVE")
            return "SAVE"

    def _answer_question_with_image(self, message: str, image_base64: str, language: str = "vi") -> str:
        """Answer the user's question using the plant image."""
        data_url = self._normalize_to_data_url(image_base64)
        if data_url is None:
            return (
                "I couldn't read the image. Please upload a clear photo of the plant."
                if language != "vi" else
                "Tôi không thể đọc được hình ảnh. Vui lòng tải lên một bức ảnh rõ ràng của cây."
            )

        prompt = (
            f"The user has uploaded a plant image and asked: \"{message}\"\n"
            "Please analyze the image and answer their question directly, clearly, and concisely. "
            f"Your response MUST be in {'Vietnamese' if language == 'vi' else 'English'}."
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


    def _describe_image(self, image_base64: str, language: str = "vi") -> str:
        """Analyze the image and generate a dynamic description + follow-up options."""
        data_url = self._normalize_to_data_url(image_base64)
        if data_url is None:
            return (
                "I couldn't read the image. Please upload a clear photo of the plant."
                if language != "vi" else
                "Tôi không thể đọc được hình ảnh. Vui lòng tải lên một bức ảnh rõ ràng của cây."
            )

        prompt = (
            "The user has uploaded a plant image without saying anything.\n"
            "Analyze the image, describe briefly what you see (e.g. what plant/object it is), "
            "and friendly ask what they would like to do with it. Provide a few options:\n"
            "- Identify it / show care tips\n"
            "- Save / add it to their library\n"
            "- Something else?\n\n"
            f"Your entire response MUST be in {'Vietnamese' if language == 'vi' else 'English'}."
        )
        try:
            if _LANGCHAIN_AVAILABLE and self._vision_llm is not None:
                response = self._vision_llm.invoke(
                    [
                        SystemMessage(content="You are a helpful plant care assistant. Describe the image and ask what the user wants to do next."),
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
            logger.exception("Failed to invoke self._vision_llm for image description")

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
                logger.exception("Failed to call vision model %s for description", model)

        # Final static fallback if all API calls fail
        return (
            "I can see a plant in this image! 🌱 What would you like me to do?\n"
            "- **Identify** it and tell you about it\n"
            "- **Add it to your plant library** with care reminders\n"
            "- Something else?"
            if language != "vi" else
            "Tôi thấy một cây trong hình ảnh này! 🌱 Bạn muốn tôi làm gì?\n"
            "- **Nhận dạng** và cho bạn biết thêm về nó\n"
            "- **Thêm vào thư viện cây** của bạn kèm lịch nhắc nhở chăm sóc\n"
            "- Điều gì khác?"
        )

    @staticmethod
    def _is_schedule_management_request(message: str) -> bool:
        normalized = message.strip().lower()
        if not normalized:
            return False

        schedule_terms = (
            "schedule",
            "schedules",
            "reminder",
            "reminders",
            "task",
            "tasks",
            "water",
            "watering",
            "fertilize",
            "fertilizing",
            "repot",
            "repotting",
            "prune",
            "pruning",
            "mist",
            "misting",
        )
        mutation_terms = (
            "create",
            "add",
            "set",
            "make",
            "remind me",
            "update",
            "edit",
            "change",
            "delete",
            "remove",
            "cancel",
        )
        schedule_as_verb = re.search(
            r"\bschedule\s+(?:a|an|my|the)?\s*"
            r"(?:water|watering|fertiliz|repot|prun|mist|reminder|task)",
            normalized,
        )
        return (
            any(term in normalized for term in schedule_terms)
            and (any(term in normalized for term in mutation_terms) or schedule_as_verb is not None)
        )

    @staticmethod
    def _classify_user_insight_request(message: str) -> str | None:
        normalized = message.strip().lower()
        if not normalized:
            return None

        if LangGraphChatAgent._is_schedule_management_request(normalized):
            return None

        journal_keywords = (
            "journal",
            "journals",
            "note",
            "notes",
            "log",
            "logs",
            "history",
            "record",
            "recorded",
            "write",
            "wrote",
            "entry",
            "entries",
            "progress",
            "symptom",
            "symptoms",
            "observation",
            "observations",
        )
        plant_keywords = (
            "my plant",
            "my plants",
            "plant",
            "plants",
            "saved",
            "library",
            "species",
            "care",
            "water",
            "sunlight",
            "fertilizer",
            "humidity",
            "temperature",
            "soil",
            "pest",
            "disease",
            "toxic",
            "paused",
            "profile",
            "task",
            "tasks",
            "reminder",
            "reminders",
            "schedule",
            "schedules",
            "completion",
            "completions",
            "completed",
            "missed",
            "overdue",
            "due",
        )
        if any(keyword in normalized for keyword in journal_keywords):
            return "journal"
        if any(keyword in normalized for keyword in plant_keywords):
            return "plant"
        return None

    @staticmethod
    def _is_small_talk_request(message: str) -> bool:
        normalized = re.sub(r"[^a-z0-9\s']", " ", message.strip().lower())
        tokens = normalized.split()
        if not tokens or len(tokens) > 8:
            return False

        small_talk_phrases = (
            "hi",
            "hello",
            "hey",
            "good morning",
            "good afternoon",
            "good evening",
            "thanks",
            "thank you",
            "bye",
            "goodbye",
            "how are you",
            "how's it going",
            "whats up",
            "what's up",
        )
        compact = " ".join(tokens)
        if compact in small_talk_phrases:
            return True
        return tokens[0] in {"hi", "hello", "hey"} and len(tokens) <= 4

    def _local_known_intent_response(
        self,
        message: str,
        db: Session | None,
        user_id: str | None,
        language: str,
    ) -> AgentChatResponse | None:
        fallback_response = self._fallback_user_insight_response(message, db, user_id)
        if fallback_response is not None:
            return fallback_response
        if self._is_small_talk_request(message):
            return AgentChatResponse(
                reply=generate_small_talk_response(message, language=language),
                tool_calls=[AgentToolCall(name="small_talk_tool")],
            )
        return None

    @staticmethod
    def _markdown_text(value: Any, fallback: str = "") -> str:
        text = str(value if value is not None else fallback).strip()
        return text.replace("|", "\\|")

    @staticmethod
    def _markdown_time(value: Any) -> str:
        text = str(value or "").strip()
        if len(text) >= 5 and text[2] == ":":
            return text[:5]
        return text

    @staticmethod
    def _summarize_plant_insight(payload: dict[str, Any]) -> str:
        if payload.get("status") != "ok":
            return str(payload.get("message") or "I could not read your saved plant data right now.")
        if payload.get("total_count", 0) == 0:
            return "You do not have any saved plants yet."
        if payload.get("matched_count", 0) == 0:
            return "I found saved plants, but none matched that question."

        items = payload.get("items", [])
        if not isinstance(items, list) or not items:
            return "I found matching saved plants, but there are no details to summarize."
        missed_tasks = payload.get("missed_tasks")
        if isinstance(missed_tasks, list):
            date_filter = payload.get("date_filter")
            filtered_date = None
            if isinstance(date_filter, dict):
                filtered_date = date_filter.get("date")
            if not missed_tasks:
                date_suffix = f" for {filtered_date}" if filtered_date else ""
                return f"**No missed plant tasks{date_suffix}.**"
            rows = [
                "| Plant | Task | Time |",
            ]
            for task in missed_tasks:
                if not isinstance(task, dict):
                    continue
                plant_name = LangGraphChatAgent._markdown_text(task.get("plant_name"), "Unknown plant")
                action_type = task.get("action_type")
                action_name = None
                if isinstance(action_type, dict):
                    action_name = action_type.get("name")
                rows.append(
                    "| "
                    f"{plant_name} | "
                    f"{LangGraphChatAgent._markdown_text(action_name, 'Task')} | "
                    f"{LangGraphChatAgent._markdown_time(task.get('scheduled_time'))} |"
                )
            date_suffix = f" for {filtered_date}" if filtered_date else ""
            count = payload.get("missed_task_count", max(0, len(rows) - 2))
            return f"**You missed {count} scheduled plant task(s){date_suffix}.**\n\n" + "\n".join(rows)
        lines = []
        for item in items:
            if not isinstance(item, dict):
                continue
            details = []
            species = item.get("species")
            if species:
                details.append(f"species: {species}")
            if item.get("is_paused"):
                details.append("paused")
            note = item.get("profile_note")
            if note:
                details.append(f"note: {note}")
            care = item.get("water") or item.get("sunlight") or item.get("soil")
            if care:
                details.append(f"care: {care}")
            schedules = item.get("schedules")
            if isinstance(schedules, list):
                task_completion_count = sum(
                    len(schedule.get("task_completions", []))
                    for schedule in schedules
                    if isinstance(schedule, dict)
                )
                details.append(
                    f"schedules: {len(schedules)}, task completions: {task_completion_count}"
                )
            suffix = f" ({'; '.join(details)})" if details else ""
            plant_name = LangGraphChatAgent._markdown_text(item.get("name"), "Unnamed plant")
            lines.append(f"- **{plant_name}**{suffix}")
        return f"**Saved plants found: {payload.get('matched_count')}**\n\n" + "\n".join(lines)

    @staticmethod
    def _summarize_journal_insight(payload: dict[str, Any]) -> str:
        if payload.get("status") != "ok":
            return str(payload.get("message") or "I could not read your journal data right now.")
        if payload.get("total_count", 0) == 0:
            return "You do not have any plant journal entries yet."
        if payload.get("matched_count", 0) == 0:
            return "I found journal entries, but none matched that question."

        items = payload.get("items", [])
        if not isinstance(items, list) or not items:
            return "I found matching journal entries, but there are no details to summarize."
        lines = []
        for item in items:
            if not isinstance(item, dict):
                continue
            entry_date = item.get("entry_date") or "unknown date"
            plant_name = LangGraphChatAgent._markdown_text(item.get("plant_name"), "Unknown plant")
            content = LangGraphChatAgent._markdown_text(item.get("content"))
            lines.append(f"- **{entry_date} - {plant_name}:** {content}")
        return f"**Journal entries found: {payload.get('matched_count')}**\n\n" + "\n".join(lines)

    def _fallback_user_insight_response(
        self,
        message: str,
        db: Session | None,
        user_id: str | None,
    ) -> AgentChatResponse | None:
        insight_intent = self._classify_user_insight_request(message)
        if insight_intent not in {"plant", "journal"}:
            return None

        if db is None or not user_id:
            payload = {"status": "error", "message": "User insight context is unavailable for this request."}
            if insight_intent == "plant":
                return AgentChatResponse(
                    reply=self._summarize_plant_insight(payload),
                    tool_calls=[AgentToolCall(name="users_plant_insight_tool")],
                )
            return AgentChatResponse(
                reply=self._summarize_journal_insight(payload),
                tool_calls=[AgentToolCall(name="users_journal_insight_tool")],
            )

        db_token, user_id_token = set_user_insight_context(db, user_id)
        try:
            if insight_intent == "plant":
                payload = get_user_plant_insight_payload(query=message)
                return AgentChatResponse(
                    reply=self._summarize_plant_insight(payload),
                    tool_calls=[AgentToolCall(name="users_plant_insight_tool")],
                )
            payload = get_user_journal_insight_payload(query=message)
            return AgentChatResponse(
                reply=self._summarize_journal_insight(payload),
                tool_calls=[AgentToolCall(name="users_journal_insight_tool")],
            )
        finally:
            reset_user_insight_context(db_token, user_id_token)

    def _update_graph_history(
        self,
        thread_id: str | None,
        user_content: str,
        assistant_content: str,
        language: str = "en",
    ) -> None:
        """Update LangGraph state with a user+assistant exchange (no DB write)."""
        if not thread_id or self._graph is None or not _LANGCHAIN_AVAILABLE:
            return
        config = {"configurable": {"thread_id": thread_id}}
        try:
            snapshot = self._graph.get_state(config)
            has_history = bool(snapshot.values and snapshot.values.get("messages"))
        except Exception:
            has_history = False

        new_messages = []
        if not has_history:
            sys_prompt = self._get_system_prompt(language)
            new_messages.append(SystemMessage(content=sys_prompt))
        else:
            new_messages.append(SystemMessage(
                content="Respond in Vietnamese language." if language == "vi" else "Respond in English language."
            ))
        new_messages.append(HumanMessage(content=user_content))
        new_messages.append(AIMessage(content=assistant_content))
        try:
            self._graph.update_state(config, {"messages": new_messages})
        except Exception:
            logger.exception("Failed to update LangGraph state")

    def _auto_save_plant(
        self,
        detected: PlantDetectionData,
        image_base64: str,
        user_id: str,
        db: Session,
        language: str = "en",
    ) -> dict[str, Any] | None:
        """Detect plant from image, save image file, persist Plant row to DB. Returns saved plant data or None on failure."""
        from app.models.plant import Plant as PlantModel
        try:
            image_path = _save_base64_image(image_base64, user_id)
        except ValueError:
            logger.warning("_auto_save_plant: failed to save image for user_id=%s", user_id)
            image_path = ""

        try:
            plant = PlantModel(
                user_id=user_id,
                name=detected.plant_name,
                species=detected.species,
                image_path=image_path or None,
                note=detected.note,
                overview=detected.overview,
                water=detected.water,
                sunlight=detected.sunlight,
                fertilizer=detected.fertilizer,
                propagating=detected.propagating,
                varieties=",".join(detected.varieties) if detected.varieties else None,
                humidity=detected.humidity,
                temperature=detected.temperature,
                soil=detected.soil,
                running=detected.running,
                potting_and_repotting=detected.potting_and_repotting,
                pests_and_diseases=detected.pests_and_diseases,
                toxicity=detected.toxicity,
                propagation=detected.propagation,
            )
            db.add(plant)
            db.commit()
            db.refresh(plant)
            logger.info(
                "_auto_save_plant: saved plant id=%s name=%r for user_id=%s",
                plant.id, detected.plant_name, user_id,
            )
            return {"plant_name": detected.plant_name, "plant_id": str(plant.id)}
        except Exception:
            db.rollback()
            logger.exception("_auto_save_plant: DB save failed for user_id=%s", user_id)
            return None


    def chat(
        self,
        message: str,
        image_base64: str | None = None,
        thread_id: str | None = None,
        language: str = "vi",
        db: Session | None = None,
        user_id: str | None = None,
        timezone: str = "UTC",
        local_time: str | None = None,
    ) -> AgentChatResponse:
        if image_base64 and thread_id:
            self._last_uploaded_image[thread_id] = image_base64

        if not image_base64 and thread_id and thread_id in self._last_uploaded_image:
            message_stripped = (message or "").strip()
            if message_stripped and self._classify_intent(message_stripped) == "SAVE":
                image_base64 = self._last_uploaded_image[thread_id]

        if image_base64:
            message_stripped = (message or "").strip()

            # ── Case 1: image with NO text → ask the user what they want ──
            if not message_stripped:
                reply_content = self._describe_image(image_base64, language=language)
                self._update_graph_history(
                    thread_id=thread_id,
                    user_content="[Gửi ảnh cây]" if language == "vi" else "[Sent a plant image]",
                    assistant_content=reply_content,
                    language=language,
                )
                return AgentChatResponse(reply=reply_content, tool_calls=[])

            # ── Case 2: image + text → classify intent ──
            intent = self._classify_intent(message_stripped)

            if intent == "QUESTION":
                try:
                    reply_content = self._answer_question_with_image(message_stripped, image_base64, language=language)
                except TypeError:
                    reply_content = self._answer_question_with_image(message_stripped, image_base64)
                self._update_graph_history(
                    thread_id=thread_id,
                    user_content=f"{message_stripped} [Uploaded a plant image.]",
                    assistant_content=reply_content,
                    language=language,
                )
                return AgentChatResponse(reply=reply_content, tool_calls=[])

            # intent == "SAVE" → detect and auto-save
            try:
                detected = self._detect_plant(image_base64, language=language)
            except TypeError:
                detected = self._detect_plant(image_base64)

            if detected is None:
                if self._last_plant_image_failure_reason == "provider_error":
                    reply_content = (
                        "Image analysis is temporarily unavailable. Please try again in a moment."
                        if language != "vi" else
                        "Phân tích hình ảnh tạm thời không khả dụng. Vui lòng thử lại sau."
                    )
                elif self._last_plant_image_failure_reason == "invalid_image":
                    reply_content = (
                        "I couldn't read that image clearly. Please send a clearer photo of the plant."
                        if language != "vi" else
                        "Tôi không đọc được ảnh này rõ. Vui lòng gửi ảnh rõ hơn của cây."
                    )
                else:
                    reply_content = (
                        "I couldn't detect a plant in this image. Please try a clearer photo with better lighting."
                        if language != "vi" else
                        "Tôi không phát hiện được cây trong ảnh này. Vui lòng thử ảnh rõ hơn với ánh sáng tốt hơn."
                    )
                self._update_graph_history(
                    thread_id=thread_id,
                    user_content=f"{message_stripped} [Uploaded a plant image.]",
                    assistant_content=reply_content,
                    language=language,
                )
                return AgentChatResponse(reply=reply_content, tool_calls=[])

            # Save image and persist plant to DB
            saved_plant_data = None
            if db is not None and user_id is not None:
                saved_plant_data = self._auto_save_plant(detected, image_base64, user_id, db, language)

            if saved_plant_data is not None:
                plant_name = saved_plant_data.get("plant_name", detected.plant_name)
                reply_content = (
                    f"✅ **{plant_name}** has been saved to your plant library!\n\n"
                    f"🌿 *{detected.species}*\n"
                    + (f"\n{detected.note}" if detected.note else "")
                    if language != "vi" else
                    f"✅ **{plant_name}** đã được lưu vào thư viện cây của bạn!\n\n"
                    f"🌿 *{detected.species}*\n"
                    + (f"\n{detected.note}" if detected.note else "")
                )
            else:
                # DB unavailable — still show detection info
                reply_content = (
                    f"I detected **{detected.plant_name}** (*{detected.species}*). "
                    "However, I was unable to save it to your library right now. Please try again."
                    if language != "vi" else
                    f"Tôi phát hiện **{detected.plant_name}** (*{detected.species}*). "
                    "Tuy nhiên, tôi không thể lưu vào thư viện của bạn lúc này. Vui lòng thử lại."
                )

            self._update_graph_history(
                thread_id=thread_id,
                user_content=f"{message_stripped} [Uploaded a plant image.]",
                assistant_content=reply_content,
                language=language,
            )
            return AgentChatResponse(
                reply=reply_content,
                tool_calls=[AgentToolCall(name="plant_image_detect_tool")],
                plant_id=saved_plant_data.get("plant_id") if saved_plant_data else None,
            )

        known_intent_response = self._local_known_intent_response(message, db, user_id, language)
        if known_intent_response is not None:
            return known_intent_response

        if not self._llm_enabled:
            return AgentChatResponse(
                reply=generate_small_talk_response(message, language=language),
                tool_calls=[AgentToolCall(name="small_talk_tool")],
            )

        try:
            response_messages = self._invoke_graph(
                message,
                thread_id=thread_id,
                language=language,
                db=db,
                user_id=user_id,
                timezone=timezone,
                local_time=local_time,
            )
        except Exception:
            fallback_response = self._fallback_user_insight_response(message, db, user_id)
            if fallback_response is not None:
                logger.exception("LangGraph chat failed; returned local user insight fallback")
                return fallback_response
            raise
        reply = self._extract_final_reply(response_messages)
        tool_calls = self._extract_tool_calls(response_messages)
        sched_id = _last_interacted_schedule_id.get()
        return AgentChatResponse(reply=reply, tool_calls=tool_calls, schedule_id=sched_id)

    def _save_both_histories(
        self,
        db: Session,
        user_id: str,
        thread_id: str,
        user_message: str,
        assistant_sql_message: str,
        assistant_graph_message: str,
        language: str = "vi",
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
                sys_prompt = self._get_system_prompt(language)
                new_messages.append(SystemMessage(content=sys_prompt))
            else:
                new_messages.append(SystemMessage(content="Respond in Vietnamese language." if language == "vi" else "Respond in English language."))
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
        language: str = "vi",
    ) -> PlantImageAnalyzeResponse:
        if message and not is_manual_creation:
            intent = self._classify_intent(message)
            if intent == "QUESTION":
                try:
                    reply = self._answer_question_with_image(message, image_base64, language=language)
                except TypeError:
                    reply = self._answer_question_with_image(message, image_base64)
                if thread_id:
                    user_text = message.strip()
                    if not user_text:
                        user_text = "Uploaded a plant image."
                    else:
                        user_text = f"{user_text} [Uploaded a plant image.]"
                    self._save_both_histories(db, user_id, thread_id, user_text, reply, reply, language=language)
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
                            if language != "vi" else
                            "Một quyết định vẫn đang chờ xử lý cho hình ảnh trước đó của bạn. "
                            "Vui lòng chấp nhận, từ chối hoặc chỉnh sửa kết quả đó trước khi gửi hình ảnh khác."
                        )
                        if thread_id:
                            user_text = message.strip() if message else ""
                            if not user_text:
                                user_text = "Uploaded a plant image."
                            else:
                                user_text = f"{user_text} [Uploaded a plant image.]"
                            self._save_both_histories(db, user_id, thread_id, user_text, reply, reply, language=language)
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
                                if language != "vi" else
                                "Một quyết định vẫn đang chờ xử lý cho hình ảnh trước đó của bạn. "
                                "Vui lòng chấp nhận, từ chối hoặc chỉnh sửa kết quả đó trước khi gửi hình ảnh khác."
                            )
                            if thread_id:
                                user_text = message.strip() if message else ""
                                if not user_text:
                                    user_text = "Uploaded a plant image."
                                else:
                                    user_text = f"{user_text} [Uploaded a plant image.]"
                                self._save_both_histories(db, user_id, thread_id, user_text, reply, reply, language=language)
                            return PlantImageAnalyzeResponse(
                                status="detected",
                                reply=reply,
                                proposal_id=pending_proposal_id,
                                data=pending_data_with_url,
                                decision_required=True,
                                decision_options=["accept", "reject", "edit"],
                            )

        try:
            detected = self._detect_plant(image_base64, language=language)
        except TypeError:
            detected = self._detect_plant(image_base64)
        if detected is None:
            if self._last_plant_image_failure_reason == "provider_error":
                reply = (
                    "Image analysis is temporarily unavailable due to an AI service issue. "
                    "Please try again in a moment."
                    if language != "vi" else
                    "Phân tích hình ảnh tạm thời không khả dụng do sự cố dịch vụ AI. Vui lòng thử lại sau giây lát."
                )
            elif self._last_plant_image_failure_reason == "invalid_image":
                reply = (
                    "I couldn't read that image format clearly. "
                    "Please send another photo with better lighting and a closer view of the plant."
                    if language != "vi" else
                    "Tôi không thể đọc rõ định dạng hình ảnh đó. Vui lòng gửi một bức ảnh khác có ánh sáng tốt hơn và góc nhìn cận cảnh hơn."
                )
            else:
                reply = (
                    "I couldn't clearly detect a plant from this image yet. Please try another photo with better lighting and a closer view of the plant."
                    if language != "vi" else
                    "Tôi chưa thể phát hiện rõ ràng một loại cây nào từ hình ảnh này. Vui lòng thử một bức ảnh khác có ánh sáng tốt hơn và góc nhìn cận cảnh hơn."
                )

            if thread_id:
                user_text = message.strip() if message else ""
                if not user_text:
                    user_text = "Uploaded a plant image."
                else:
                    user_text = f"{user_text} [Uploaded a plant image.]"
                self._save_both_histories(db, user_id, thread_id, user_text, reply, reply, language=language)

            return PlantImageAnalyzeResponse(
                status="not_detected",
                reply=reply,
                decision_required=False,
            )

        try:
            image_path = _save_base64_image(image_base64, user_id)
        except ValueError:
            reply = (
                "Invalid image format. Please try another photo."
                if language != "vi" else
                "Định dạng hình ảnh không hợp lệ. Vui lòng thử một bức ảnh khác."
            )
            if thread_id:
                user_text = message.strip() if message else ""
                if not user_text:
                    user_text = "Uploaded a plant image."
                else:
                    user_text = f"{user_text} [Uploaded a plant image.]"
                self._save_both_histories(db, user_id, thread_id, user_text, reply, reply, language=language)
            return PlantImageAnalyzeResponse(
                status="not_detected",
                reply=reply,
                decision_required=False,
            )

        if is_manual_creation:
            reply = (
                "I detected a plant and prepared the information below."
                if language != "vi" else
                "Tôi đã phát hiện ra một cây trồng và chuẩn bị thông tin bên dưới."
            )
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
            if language != "vi" else
            "Tôi đã phát hiện ra một loại cây và chuẩn bị thông tin bên dưới. "
            "Vui lòng xem lại và cho tôi biết nếu tôi có thể sử dụng thông tin này hoặc nếu bạn muốn chỉnh sửa nó."
        )

        if thread_id:
            user_text = message.strip() if message else ""
            if not user_text:
                user_text = "Uploaded a plant image."
            else:
                user_text = f"{user_text} [Uploaded a plant image.]"
            
            desc_parts = []
            if language == "vi":
                desc_parts.append(f"Tôi đã phát hiện ra một loại cây: {detected.plant_name} ({detected.species}).")
                if detected.note:
                    desc_parts.append(f"Ghi chú chăm sóc: {detected.note}.")
                if detected.overview:
                    desc_parts.append(f"Tổng quan: {detected.overview}")
                if detected.water:
                    desc_parts.append(f"Tưới nước: {detected.water}")
                if detected.sunlight:
                    desc_parts.append(f"Ánh sáng: {detected.sunlight}")
            else:
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
            self._save_both_histories(db, user_id, thread_id, user_text, reply, assistant_graph_text, language=language)

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
        language: str = "vi",
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
            language=language,
        )

        if thread_id and response.status != "invalid":
            if decision == "accept":
                user_text = (
                    f"I accept the proposal to add the plant: {plant_name} ({species})."
                    if language != "vi" else
                    f"Tôi chấp nhận đề xuất thêm cây: {plant_name} ({species})."
                )
            elif decision == "reject":
                user_text = (
                    f"I reject the proposal to add the plant: {plant_name} ({species})."
                    if language != "vi" else
                    f"Tôi từ chối đề xuất thêm cây: {plant_name} ({species})."
                )
            elif decision == "edit":
                user_text = (
                    f"I edited the proposal for the plant: {plant_name} ({species})."
                    if language != "vi" else
                    f"Tôi đã chỉnh sửa đề xuất cho cây: {plant_name} ({species})."
                )
                if edited_data:
                    user_text += (
                        f" New details: Name={edited_data.plant_name}, Species={edited_data.species}, Note={edited_data.note}."
                        if language != "vi" else
                        f" Chi tiết mới: Tên={edited_data.plant_name}, Loài={edited_data.species}, Ghi chú={edited_data.note}."
                    )
            else:
                user_text = (
                    f"Decision made: {decision} on plant proposal."
                    if language != "vi" else
                    f"Đã đưa ra quyết định: {decision} trên đề xuất cây."
                )
            
            self._save_both_histories(db, user_id, thread_id, user_text, response.reply, response.reply, language=language)

        return response

    def _apply_plant_decision_internal(
        self,
        proposal_id: str,
        decision: str,
        edited_data: PlantDetectionData | None,
        user_id: str,
        db: Session,
        language: str = "vi",
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
                        reply=(
                            "This decision request is no longer valid. Please send the image again."
                            if language != "vi" else
                            "Yêu cầu quyết định này không còn hiệu lực. Vui lòng gửi lại hình ảnh."
                        ),
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
                        reply=(
                            "Accepted. I will use this plant information."
                            if language != "vi" else
                            "Đã chấp nhận. Tôi sẽ sử dụng thông tin cây này."
                        ),
                        data=accepted_data,
                    )

                if decision == "reject":
                    current.status = "rejected"
                    db.commit()
                    return PlantDecisionResponse(
                        status="rejected",
                        reply=(
                            "Understood. I discarded this detected result."
                            if language != "vi" else
                            "Đã hiểu. Tôi đã loại bỏ kết quả phát hiện này."
                        ),
                    )

                if decision == "edit":
                    if edited_data is None:
                        return PlantDecisionResponse(
                            status="invalid",
                            reply=(
                                "Please include edited_data when decision is edit."
                                if language != "vi" else
                                "Vui lòng bao gồm edited_data khi quyết định là chỉnh sửa."
                            ),
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
                        reply=(
                            "Updated. I will use your edited plant information."
                            if language != "vi" else
                            "Đã cập nhật. Tôi sẽ sử dụng thông tin cây đã chỉnh sửa của bạn."
                        ),
                        data=edited_data,
                    )
            except ProgrammingError:
                db.rollback()
                current = self._proposal_store.get(proposal_id)
                owner_id = self._proposal_owner_by_id.get(proposal_id)
                if current is None or owner_id != user_id:
                    return PlantDecisionResponse(
                        status="invalid",
                        reply=(
                            "This decision request is no longer valid. Please send the image again."
                            if language != "vi" else
                            "Yêu cầu quyết định này không còn hiệu lực. Vui lòng gửi lại hình ảnh."
                        ),
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
                        reply=(
                            "Accepted. I will use this plant information."
                            if language != "vi" else
                            "Đã chấp nhận. Tôi sẽ sử dụng thông tin cây này."
                        ),
                        data=accepted_data_with_url,
                    )
                if decision == "reject":
                    self._proposal_store.pop(proposal_id, None)
                    self._proposal_owner_by_id.pop(proposal_id, None)
                    self._pending_proposal_by_owner.pop(user_id, None)
                    return PlantDecisionResponse(
                        status="rejected",
                        reply=(
                            "Understood. I discarded this detected result."
                            if language != "vi" else
                            "Đã hiểu. Tôi đã loại bỏ kết quả phát hiện này."
                        ),
                    )
                if decision == "edit":
                    if edited_data is None:
                        return PlantDecisionResponse(
                            status="invalid",
                            reply=(
                                "Please include edited_data when decision is edit."
                                if language != "vi" else
                                "Vui lòng bao gồm edited_data khi quyết định là chỉnh sửa."
                            ),
                        )
                    self._proposal_store.pop(proposal_id, None)
                    self._proposal_owner_by_id.pop(proposal_id, None)
                    self._pending_proposal_by_owner.pop(user_id, None)
                    return PlantDecisionResponse(
                        status="edited",
                        reply=(
                            "Updated. I will use your edited plant information."
                            if language != "vi" else
                            "Đã cập nhật. Tôi sẽ sử dụng thông tin cây đã chỉnh sửa của bạn."
                        ),
                        data=edited_data,
                    )

        return PlantDecisionResponse(
            status="invalid",
            reply=(
                "Unsupported decision."
                if language != "vi" else
                "Quyết định không được hỗ trợ."
            ),
        )

    async def chat_stream(
        self,
        message: str,
        language: str = "vi",
        timezone: str = "UTC",
        local_time: str | None = None,
    ) -> AsyncIterator[str]:
        if not self._llm_enabled or self._llm is None:
            fallback_reply = generate_small_talk_response(message)
            yield self._sse("chunk", fallback_reply)
            yield self._sse("done", json.dumps({"reply": fallback_reply}))
            return

        full_reply = ""
        async for chunk in self._llm.astream(
            [
                SystemMessage(content=self._get_system_prompt(language, timezone, local_time)),
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
        language: str = "vi",
        db: Session | None = None,
        user_id: str | None = None,
        timezone: str = "UTC",
        local_time: str | None = None,
    ) -> Sequence[BaseMessage]:
        if self._graph is None:
            return [AIMessage(content=generate_small_talk_response(message))]

        db_token = None
        user_id_token = None
        schedule_id_token = None
        tz_token = None
        lt_token = None
        if db is not None and user_id:
            db_token, user_id_token = set_user_insight_context(db, user_id)
            from app.agent_tools.user_insights import _user_timezone, _user_local_time
            tz_token = _user_timezone.set(timezone)
            lt_token = _user_local_time.set(local_time)
            schedule_id_token = _last_interacted_schedule_id.set(None)

        state: dict[str, Any]
        try:
            sys_prompt = self._get_system_prompt(language, timezone, local_time)
            if thread_id is None:
                state = self._graph.invoke(
                    {
                        "messages": [
                            SystemMessage(content=sys_prompt),
                            HumanMessage(content=message),
                        ]
                    }
                )
                return cast(Sequence[BaseMessage], state["messages"])

            config = {"configurable": {"thread_id": thread_id}}
            previous_message_count = 0
            has_history = False
            try:
                snapshot = self._graph.get_state(config)
                previous_messages = (
                    snapshot.values.get("messages")
                    if getattr(snapshot, "values", None)
                    else None
                )
                if isinstance(previous_messages, Sequence):
                    previous_message_count = len(previous_messages)
                    has_history = previous_message_count > 0
            except Exception:
                has_history = False
            has_pending_interrupt = self._thread_has_pending_interrupt(config)

            # Only resume when both conditions are true:
            # 1) caller explicitly requests resume
            # 2) this thread currently has a pending interrupt
            if resume_interrupt and has_pending_interrupt:
                state = self._graph.invoke(Command(resume=message), config=config)
                messages = cast(Sequence[BaseMessage], state["messages"])
                current_messages = messages[previous_message_count:]
                return current_messages or messages

            # New turn input for same thread_id (multi-turn chat), not a resume.
            if not has_history:
                # First message on this thread: prepend SystemMessage instructions
                state = self._graph.invoke(
                    {
                        "messages": [
                            SystemMessage(content=sys_prompt),
                            HumanMessage(content=message),
                        ]
                    },
                    config=config,
                )
            else:
                # Subsequent messages still need fresh date/time context; persisted threads
                # may contain stale system prompts from earlier days.
                state = self._graph.invoke(
                    {
                        "messages": [
                            HumanMessage(content=message),
                            SystemMessage(content=sys_prompt),
                        ]
                    },
                    config=config,
                )
            messages = cast(Sequence[BaseMessage], state["messages"])
            current_messages = messages[previous_message_count:]
            return current_messages or messages
        finally:
            if db_token is not None and user_id_token is not None:
                reset_user_insight_context(db_token, user_id_token)
                from app.agent_tools.user_insights import _user_timezone, _user_local_time
                if tz_token is not None:
                    _user_timezone.reset(tz_token)
                if lt_token is not None:
                    _user_local_time.reset(lt_token)
            if schedule_id_token is not None:
                _last_interacted_schedule_id.reset(schedule_id_token)

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
        return "I can handle small talk, plant image detection, saved plant insight, and journal insight for now."

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

    def _detect_plant(self, image_base64: str, language: str = "vi") -> PlantDetectionData | None:
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
            "Do not include markdown. Use cautious language like 'typically' or 'commonly' when uncertain. "
            f"All text values in the JSON (except the keys, which must remain exactly as specified above) MUST be written in {'Vietnamese' if language == 'vi' else 'English'}."
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
