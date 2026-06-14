from __future__ import annotations

from functools import lru_cache
import json
from urllib import error, request

from langchain_core.tools import tool

from app.core.config import settings

from typing import Annotated
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.prebuilt import InjectedState

try:
    from langchain.chat_models import init_chat_model
    _LANGCHAIN_AVAILABLE = True
except ModuleNotFoundError:
    _LANGCHAIN_AVAILABLE = False


SMALL_TALK_SYSTEM_PROMPT = """\
You are a friendly plant reminder assistant.
Reply to small talk naturally and briefly.
Keep it to one short sentence unless the user clearly asks for more.
"""


@lru_cache(maxsize=1)
def _get_small_talk_llm():
    if not _LANGCHAIN_AVAILABLE or not settings.openrouter_api_key:
        return None
    return init_chat_model(
        settings.openrouter_model,
        model_provider="openai",
        api_key=settings.openrouter_api_key,
        base_url=settings.PROXY_BASE_URL,
        default_headers={
            "HTTP-Referer": settings.openrouter_site_url or "",
            "X-OpenRouter-Title": settings.openrouter_site_name or "",
        },
        temperature=0.3,
        max_tokens=80,
    )


def _invoke_openrouter_small_talk(
    message: str,
    history: list[BaseMessage] | None = None,
    language: str = "en",
) -> tuple[str | None, str | None]:
    if not settings.openrouter_api_key:
        return None, "OPENROUTER_API_KEY is missing."

    if history:
        for msg in history:
            if isinstance(msg, SystemMessage) and "Vietnamese" in msg.content:
                language = "vi"
                break

    openai_messages = []
    system_prompt = SMALL_TALK_SYSTEM_PROMPT + (
        "\nResponse MUST be in Vietnamese language." if language == "vi" else "\nResponse MUST be in English language."
    )
    openai_messages.append({"role": "system", "content": system_prompt})

    if history:
        for msg in history:
            if isinstance(msg, SystemMessage):
                continue
            content = getattr(msg, "content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            role = "user"
            if msg.type == "assistant":
                role = "assistant"
            elif msg.type == "system":
                continue
            elif msg.type == "tool":
                continue
            openai_messages.append({"role": role, "content": content})
    else:
        openai_messages.append({"role": "user", "content": message})

    payload = {
        "model": settings.openrouter_model,
        "temperature": 0.3,
        "max_tokens": 80,
        "messages": openai_messages,
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=f"{settings.PROXY_BASE_URL.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.openrouter_site_url or "",
            "X-OpenRouter-Title": settings.openrouter_site_name or "",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        try:
            err_raw = exc.read().decode("utf-8")
            err_json = json.loads(err_raw)
            err_msg = err_json.get("error", {}).get("message")
            if isinstance(err_msg, str) and err_msg.strip():
                return None, err_msg.strip()
        except Exception:
            pass
        return None, f"OpenRouter HTTP error: {exc.code}"
    except (error.URLError, TimeoutError, OSError):
        return None, "OpenRouter request failed."

    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None, "OpenRouter response format was unexpected."

    if isinstance(content, str) and content.strip():
        return content.strip(), None
    return None, "OpenRouter returned empty content."


def generate_small_talk_response(
    message: str,
    history: list[BaseMessage] | None = None,
    language: str = "en",
) -> str:
    if history:
        for msg in history:
            if isinstance(msg, SystemMessage) and "Vietnamese" in msg.content:
                language = "vi"
                break

    system_prompt = SMALL_TALK_SYSTEM_PROMPT + (
        "\nResponse MUST be in Vietnamese language." if language == "vi" else "\nResponse MUST be in English language."
    )

    llm = _get_small_talk_llm()
    if llm is not None:
        if history:
            filtered_history = [m for m in history if not isinstance(m, SystemMessage)]
            messages_to_send = [SystemMessage(content=system_prompt)] + filtered_history
        else:
            messages_to_send = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=message),
            ]
        try:
            response = llm.invoke(messages_to_send)
            content = getattr(response, "content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
        except Exception:
            pass

    direct_response, err = _invoke_openrouter_small_talk(message, history=history, language=language)
    if direct_response:
        return direct_response

    if err:
        return f"Small talk model call failed: {err}"
    return "Small talk model call failed for an unknown reason."


@tool("small_talk_tool")
def small_talk_tool(
    message: str,
    state_messages: Annotated[list[BaseMessage], InjectedState("messages")],
) -> str:
    """Handle small-talk messages using the configured chat model."""
    return generate_small_talk_response(message, history=state_messages)
