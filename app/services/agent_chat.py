from __future__ import annotations

import json
from collections.abc import Sequence
from collections.abc import AsyncIterator
from typing import Any

try:
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    _LANGCHAIN_AVAILABLE = True
except ModuleNotFoundError:
    _LANGCHAIN_AVAILABLE = False

from app.agent_tools.small_talk import generate_small_talk_response, small_talk_tool
from app.core.config import settings
from app.schemas.chat import AgentChatResponse, AgentToolCall

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
If the user asks beyond current capability, clearly say you currently support small talk only.

Reference document context:
{OPENROUTER_QUICKSTART_CONTEXT}
"""


class LangGraphChatAgent:
    def __init__(self) -> None:
        self._llm_enabled = bool(settings.openrouter_api_key) and _LANGCHAIN_AVAILABLE
        self._llm: Any | None = None
        self._graph = self._build_graph() if self._llm_enabled else None

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
        ).bind_tools([small_talk_tool])

        tool_node = ToolNode([small_talk_tool])

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
            return AgentChatResponse(
                reply=generate_small_talk_response(message),
                tool_calls=[AgentToolCall(name="small_talk_tool")],
            )

        response_messages = self._invoke_graph(message)
        reply = self._extract_final_reply(response_messages)
        tool_calls = self._extract_tool_calls(response_messages)
        return AgentChatResponse(reply=reply, tool_calls=tool_calls)

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
        return "I can handle small talk for now."

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


agent = LangGraphChatAgent()
