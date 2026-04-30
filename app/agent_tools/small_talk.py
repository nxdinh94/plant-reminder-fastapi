from __future__ import annotations

from functools import lru_cache
import json
from urllib import error, request

from langchain_core.tools import tool

from app.core.config import settings

try:
    from langchain.chat_models import init_chat_model
    from langchain_core.messages import HumanMessage, SystemMessage

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
        base_url=settings.openrouter_base_url,
        default_headers={
            "HTTP-Referer": settings.openrouter_site_url or "",
            "X-OpenRouter-Title": settings.openrouter_site_name or "",
        },
        temperature=0.3,
        max_tokens=80,
    )


def _invoke_openrouter_small_talk(message: str) -> tuple[str | None, str | None]:
    if not settings.openrouter_api_key:
        return None, "OPENROUTER_API_KEY is missing."

    payload = {
        "model": settings.openrouter_model,
        "temperature": 0.3,
        "max_tokens": 80,
        "messages": [
            {"role": "system", "content": SMALL_TALK_SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
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


def generate_small_talk_response(message: str) -> str:
    llm = _get_small_talk_llm()
    if llm is not None:
        response = llm.invoke(
            [
                SystemMessage(content=SMALL_TALK_SYSTEM_PROMPT),
                HumanMessage(content=message),
            ]
        )
        content = getattr(response, "content", "")
        if isinstance(content, str) and content.strip():
            return content.strip()

    direct_response, err = _invoke_openrouter_small_talk(message)
    if direct_response:
        return direct_response

    if err:
        return f"Small talk model call failed: {err}"
    return "Small talk model call failed for an unknown reason."


@tool("small_talk_tool")
def small_talk_tool(message: str) -> str:
    """Handle small-talk messages using the configured chat model."""
    return generate_small_talk_response(message)
