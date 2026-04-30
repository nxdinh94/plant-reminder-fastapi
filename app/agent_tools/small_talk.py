from __future__ import annotations

from langchain_core.tools import tool


def generate_small_talk_response(message: str) -> str:
    normalized = message.strip().lower()

    if any(greeting in normalized for greeting in ("hello", "hi", "hey", "good morning", "good evening")):
        return "Hi! I can help with plant reminders and quick questions."

    if "how are you" in normalized:
        return "I am doing well and ready to help with your plant reminder tasks."

    if any(thanks in normalized for thanks in ("thanks", "thank you", "thx")):
        return "You are welcome."

    if any(bye in normalized for bye in ("bye", "goodbye", "see you")):
        return "See you later."

    return "I am here. Ask me anything about your plant reminders."


@tool("small_talk_tool")
def small_talk_tool(message: str) -> str:
    """Handle short greetings, gratitude, and other small-talk messages."""
    return generate_small_talk_response(message)
