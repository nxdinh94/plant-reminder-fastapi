from __future__ import annotations

import base64
import json
import uuid
import re
import logging
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from typing import cast
from collections.abc import Sequence
from collections.abc import AsyncIterator
from typing import Any
from threading import Lock

try:
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    _LANGCHAIN_AVAILABLE = True
except ModuleNotFoundError:
    _LANGCHAIN_AVAILABLE = False

from app.agent_tools.datetime_tool import datetime_tool, generate_datetime_response, is_datetime_request
from app.agent_tools.small_talk import generate_small_talk_response, small_talk_tool
from app.core.config import settings
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
If the user asks beyond current capability, clearly say you currently support small talk and datetime only.

Reference document context:
{OPENROUTER_QUICKSTART_CONTEXT}
"""

logger = logging.getLogger(__name__)


class LangGraphChatAgent:
    def __init__(self) -> None:
        self._llm_enabled = bool(settings.openrouter_api_key) and _LANGCHAIN_AVAILABLE
        self._vision_enabled = bool(settings.openrouter_api_key)
        self._llm: Any | None = None
        self._vision_llm: Any | None = None
        self._graph = self._build_graph() if self._llm_enabled else None
        self._proposal_store: dict[str, PlantDetectionData] = {}
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
        ).bind_tools([small_talk_tool, datetime_tool])

        tool_node = ToolNode([small_talk_tool, datetime_tool])

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
        return graph.compile()

    def chat(self, message: str) -> AgentChatResponse:
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

        response_messages = self._invoke_graph(message)
        reply = self._extract_final_reply(response_messages)
        tool_calls = self._extract_tool_calls(response_messages)
        return AgentChatResponse(reply=reply, tool_calls=tool_calls)

    def analyze_plant_image(self, image_base64: str) -> PlantImageAnalyzeResponse:
        detected = self._detect_plant(image_base64)
        if detected is None:
            return PlantImageAnalyzeResponse(
                status="not_detected",
                reply="I couldn't clearly detect a plant from this image yet. Please try another photo with better lighting and a closer view of the plant.",
                decision_required=False,
            )

        proposal_id = str(uuid.uuid4())
        with self._proposal_lock:
            self._proposal_store[proposal_id] = detected

        return PlantImageAnalyzeResponse(
            status="detected",
            reply=(
                "I detected a plant and prepared the information below. "
                "Do you want to accept, reject, or edit it?"
            ),
            proposal_id=proposal_id,
            data=detected,
            decision_required=True,
            decision_options=["accept", "reject", "edit"],
        )

    def apply_plant_decision(
        self,
        proposal_id: str,
        decision: str,
        edited_data: PlantDetectionData | None,
    ) -> PlantDecisionResponse:
        with self._proposal_lock:
            current = self._proposal_store.get(proposal_id)
            if current is None:
                return PlantDecisionResponse(
                    status="invalid",
                    reply="This decision request is no longer valid. Please send the image again.",
                )

            if decision == "accept":
                accepted_data = self._proposal_store.pop(proposal_id)
                return PlantDecisionResponse(
                    status="accepted",
                    reply="Accepted. I will use this plant information.",
                    data=accepted_data,
                )

            if decision == "reject":
                self._proposal_store.pop(proposal_id, None)
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

    def _invoke_graph(self, message: str) -> Sequence[BaseMessage]:
        if self._graph is None:
            return [AIMessage(content=generate_small_talk_response(message))]
        state = self._graph.invoke(
            {
                "messages": [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=message),
                ]
            }
        )
        return state["messages"]

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
        if not self._vision_enabled:
            logger.warning(
                "Plant image analyze skipped: vision disabled (has_api_key=%s)",
                bool(settings.openrouter_api_key),
            )
            return None

        data_url = self._normalize_to_data_url(image_base64)
        if data_url is None:
            logger.warning("Plant image analyze failed: invalid base64 payload after normalization")
            return None

        prompt = (
            "First, describe the visible things in this image in one short sentence. "
            "Then decide whether a plant is clearly present. "
            "Return strict JSON only. "
            "If a plant is clearly present, return: "
            "{\"plant_name\":\"...\",\"species\":\"...\",\"short_care_guide\":\"...\",\"description\":\"...\"}. "
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
                return None
        else:
            raw = self._invoke_vision_openrouter_rest(prompt, data_url)
        if not raw:
            logger.warning("Plant image analyze failed: empty model response")
            return None
        payload = self._parse_vision_payload(raw)
        if payload is None:
            logger.warning("Plant image analyze non-JSON response; trying text fallback snippet=%r", raw[:300])
            fallback = self._detect_plant_from_text(raw)
            if fallback is not None:
                return fallback
            return None

        if payload.get("not_detected") is True:
            logger.info("Plant image analyze result: model returned not_detected")
            return None
        try:
            plant_name = str(payload.get("plant_name") or payload.get("name") or "").strip()
            species = str(payload.get("species") or payload.get("scientific_name") or "").strip()
            short_care_guide = str(payload.get("short_care_guide") or payload.get("care_guide") or "").strip()
            if not plant_name or not species or not short_care_guide:
                logger.warning("Plant image analyze failed: JSON missing expected keys payload=%r", payload)
                return None
            return PlantDetectionData(
                plant_name=plant_name,
                species=species,
                short_care_guide=short_care_guide,
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
            short_care_guide=(
                "Place in bright indirect light, water when topsoil is dry, "
                "and avoid overwatering until species is confirmed."
            ),
        )

    def _invoke_vision_openrouter_rest(self, prompt: str, data_url: str) -> str:
        payload = {
            "model": settings.openrouter_model,
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
        except HTTPError:
            logger.exception("Plant image analyze failed: openrouter HTTP error")
            return ""
        except URLError:
            logger.exception("Plant image analyze failed: openrouter URL error")
            return ""
        except Exception:
            logger.exception("Plant image analyze failed: openrouter request error")
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
