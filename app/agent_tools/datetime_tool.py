from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from typing import Annotated
from langchain_core.tools import tool
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.prebuilt import InjectedState


_DATETIME_KEYWORDS = (
    "time",
    "date",
    "day",
    "today",
    "tomorrow",
    "yesterday",
    "now",
    "clock",
    "timezone",
)


def is_datetime_request(message: str) -> bool:
    normalized = message.strip().lower()
    return any(keyword in normalized for keyword in _DATETIME_KEYWORDS)


def generate_datetime_response(timezone_name: str = "UTC", language: str = "en") -> str:
    tz_name = timezone_name.strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz_name = "UTC"
        tz = timezone.utc

    now = datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    if language == "vi":
        return (
            f"Ngày giờ hiện tại múi giờ {tz_name}: {date_str} {time_str} "
            f"(ISO: {now.isoformat()})."
        )
    return (
        f"Current datetime in {tz_name}: {date_str} {time_str} "
        f"(ISO: {now.isoformat()})."
    )


@tool("datetime_tool")
def datetime_tool(
    timezone_name: str = "UTC",
    state_messages: Annotated[list[BaseMessage], InjectedState("messages")] | None = None,
) -> str:
    """Return the current date and time for a timezone (IANA format, e.g. Asia/Bangkok)."""
    language = "en"
    if state_messages:
        for msg in state_messages:
            if isinstance(msg, SystemMessage) and "Vietnamese" in msg.content:
                language = "vi"
                break
    return generate_datetime_response(timezone_name, language=language)
