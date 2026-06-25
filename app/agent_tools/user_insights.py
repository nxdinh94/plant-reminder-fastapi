from __future__ import annotations

import json
import re
import zoneinfo
from contextvars import ContextVar, Token
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action_type import ActionType
from app.models.note import Note
from app.models.plant import Plant
from app.models.schedule import Schedule
from app.models.task_completion import TaskCompletion


_current_db: ContextVar[Session | None] = ContextVar("user_insights_db", default=None)
_current_user_id: ContextVar[str | None] = ContextVar("user_insights_user_id", default=None)
_last_interacted_schedule_id: ContextVar[str | None] = ContextVar("last_interacted_schedule_id", default=None)
_user_timezone: ContextVar[str] = ContextVar("user_timezone", default="UTC")
_user_local_time: ContextVar[str | None] = ContextVar("user_local_time", default=None)


def set_user_insight_context(db: Session, user_id: str) -> tuple[Token[Session | None], Token[str | None]]:
    return _current_db.set(db), _current_user_id.set(user_id)


def reset_user_insight_context(
    db_token: Token[Session | None],
    user_id_token: Token[str | None],
) -> None:
    _current_db.reset(db_token)
    _current_user_id.reset(user_id_token)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _context_or_error() -> tuple[Session | None, str | None, str | None]:
    db = _current_db.get()
    user_id = _current_user_id.get()
    if db is None or not user_id:
        return None, None, "User insight context is unavailable for this request."
    return db, user_id, None


def _timezone_from_context(timezone_value: str | None) -> timezone | zoneinfo.ZoneInfo:
    if not timezone_value:
        return timezone.utc

    normalized = timezone_value.strip()
    if normalized.upper() in {"UTC", "GMT", "Z"}:
        return timezone.utc

    offset_match = re.fullmatch(
        r"(?:(?:GMT|UTC)\s*)?([+-])(\d{1,2})(?::?(\d{2}))?",
        normalized,
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
            return timezone(delta)

    try:
        return zoneinfo.ZoneInfo(normalized)
    except Exception:
        return timezone.utc


def _local_schedule_datetime_as_utc(local_date: date, local_time: time) -> datetime:
    user_tz = _timezone_from_context(_user_timezone.get())
    local_dt = datetime.combine(local_date, local_time).replace(tzinfo=user_tz)
    return local_dt.astimezone(timezone.utc)


def _coerce_query(query: Any) -> str:
    if query is None:
        return ""
    if isinstance(query, str):
        return query
    return str(query)


def _coerce_limit(limit: Any, default: int, maximum: int) -> int:
    if limit is None:
        return default
    if isinstance(limit, str):
        normalized = limit.strip().lower()
        if normalized in {"", "all", "any", "none", "null"}:
            return maximum if normalized == "all" else default
        try:
            limit = int(normalized)
        except ValueError:
            return default
    try:
        return max(1, min(int(limit), maximum))
    except (TypeError, ValueError):
        return default


def _matches_query(*values: str | None, query: str) -> bool:
    normalized = query.strip().lower()
    if not normalized:
        return True
    searchable = " ".join(value or "" for value in values).lower()
    if normalized in searchable:
        return True
    stopwords = {
        "about",
        "have",
        "tell",
        "what",
        "when",
        "where",
        "which",
        "write",
        "wrote",
        "record",
        "recorded",
        "plant",
        "plants",
        "journal",
        "journals",
        "entry",
        "entries",
        "note",
        "notes",
    }
    tokens = [
        token.strip(".,?!:;()[]{}\"'")
        for token in normalized.split()
        if len(token.strip(".,?!:;()[]{}\"'")) >= 3
    ]
    meaningful_tokens = [token for token in tokens if token not in stopwords]
    if not meaningful_tokens:
        return True
    return any(token in searchable for token in meaningful_tokens)


def _is_generic_plant_query(query: str) -> bool:
    normalized = query.strip().lower()
    if not normalized:
        return True
    generic_markers = (
        "plant",
        "plants",
        "my plant",
        "my plants",
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
        "plants do i have",
        "saved plants",
        "plant list",
        "list plants",
        "all plants",
    )
    return any(marker in normalized for marker in generic_markers)


def _parse_query_date_filter(query: str, *, today: date | None = None) -> tuple[date | None, str | None]:
    normalized = query.strip().lower()
    if not normalized:
        return None, None

    base_date = today or date.today()
    if re.search(r"\byesterday\b", normalized):
        return base_date - timedelta(days=1), "yesterday"
    if re.search(r"\btoday\b", normalized):
        return base_date, "today"
    if re.search(r"\btomorrow\b", normalized):
        return base_date + timedelta(days=1), "tomorrow"

    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", normalized)
    if iso_match:
        try:
            return date.fromisoformat(iso_match.group(1)), "explicit"
        except ValueError:
            return None, None
    return None, None


def _asks_for_missed_tasks(query: str) -> bool:
    normalized = query.strip().lower()
    if not normalized:
        return False
    task_markers = ("task", "tasks", "schedule", "schedules", "reminder", "reminders")
    missed_markers = ("missed", "missing", "overdue", "not completed", "incomplete")
    return any(marker in normalized for marker in task_markers) and any(
        marker in normalized for marker in missed_markers
    )


def _schedule_due_on(schedule: Schedule, target_date: date) -> bool:
    start_date = schedule.start_date
    if start_date is not None and target_date < start_date:
        return False

    frequency_type = (schedule.frequency_type or "").strip().upper()
    if frequency_type == "INTERVAL":
        if start_date is None or not schedule.frequency_days or schedule.frequency_days <= 0:
            return False
        elapsed_days = (target_date - start_date).days
        return elapsed_days % schedule.frequency_days == 0

    if frequency_type == "SPECIFIC_DAYS":
        weekday_names = {
            "MONDAY": 0,
            "MON": 0,
            "TUESDAY": 1,
            "TUE": 1,
            "WEDNESDAY": 2,
            "WED": 2,
            "THURSDAY": 3,
            "THU": 3,
            "FRIDAY": 4,
            "FRI": 4,
            "SATURDAY": 5,
            "SAT": 5,
            "SUNDAY": 6,
            "SUN": 6,
        }
        return any(
            weekday_names.get(str(day).strip().upper()) == target_date.weekday()
            for day in schedule.days_of_week or []
        )

    return schedule.next_due_at is not None and schedule.next_due_at.date() == target_date


def _missed_task_payload(
    *,
    plant: Plant,
    schedule: Schedule,
    action_type: ActionType | None,
    target_date: date,
) -> dict[str, Any]:
    return {
        "date": target_date,
        "plant_id": plant.id,
        "plant_name": plant.name,
        "schedule_id": schedule.id,
        "action_type_id": schedule.action_type_id,
        "action_type": (
            {
                "id": action_type.id,
                "name": action_type.name,
                "icon": action_type.icon,
                "color": action_type.color,
            }
            if action_type is not None
            else None
        ),
        "scheduled_time": schedule.scheduled_time,
        "note": schedule.note,
    }


def _is_generic_journal_query(query: str) -> bool:
    normalized = query.strip().lower()
    if not normalized:
        return True
    generic_markers = (
        "journal",
        "journals",
        "notes",
        "my journal",
        "my journals",
        "journal entries",
        "all notes",
        "my notes",
        "what did i record",
    )
    return any(marker in normalized for marker in generic_markers)


def _task_completion_payload(task_completion: TaskCompletion) -> dict[str, Any]:
    return {
        "id": task_completion.id,
        "user_id": task_completion.user_id,
        "schedule_id": task_completion.schedule_id,
        "completion_date": task_completion.completion_date,
        "completed_at": task_completion.completed_at,
        "created_at": task_completion.created_at,
        "updated_at": task_completion.updated_at,
        "deleted_at": task_completion.deleted_at,
        "version": task_completion.version,
    }


def _schedule_payload(
    schedule: Schedule,
    *,
    action_type: ActionType | None,
    task_completions: list[TaskCompletion],
) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "user_id": schedule.user_id,
        "plant_id": schedule.plant_id,
        "action_type_id": schedule.action_type_id,
        "action_type": (
            {
                "id": action_type.id,
                "name": action_type.name,
                "icon": action_type.icon,
                "color": action_type.color,
            }
            if action_type is not None
            else None
        ),
        "frequency_type": schedule.frequency_type,
        "frequency_days": schedule.frequency_days,
        "days_of_week": schedule.days_of_week,
        "scheduled_time": schedule.scheduled_time,
        "note": schedule.note,
        "last_completed_at": schedule.last_completed_at,
        "next_due_at": schedule.next_due_at,
        "start_date": schedule.start_date,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
        "deleted_at": schedule.deleted_at,
        "version": schedule.version,
        "task_completions": [_task_completion_payload(item) for item in task_completions],
    }


def _plant_payload(
    plant: Plant,
    *,
    schedules: list[Schedule],
    action_types_by_id: dict[str, ActionType],
    task_completions_by_schedule_id: dict[str, list[TaskCompletion]],
) -> dict[str, Any]:
    return {
        "id": plant.id,
        "user_id": plant.user_id,
        "name": plant.name,
        "species": plant.species,
        "potted_date": plant.potted_date,
        "image_path": plant.image_path,
        "is_paused": plant.is_paused,
        "profile_note": plant.note,
        "note": plant.note,
        "overview": plant.overview,
        "water": plant.water,
        "sunlight": plant.sunlight,
        "fertilizer": plant.fertilizer,
        "propagating": plant.propagating,
        "varieties": plant.varieties,
        "humidity": plant.humidity,
        "temperature": plant.temperature,
        "soil": plant.soil,
        "running": plant.running,
        "potting_and_repotting": plant.potting_and_repotting,
        "pests_and_diseases": plant.pests_and_diseases,
        "toxicity": plant.toxicity,
        "propagation": plant.propagation,
        "created_at": plant.created_at,
        "updated_at": plant.updated_at,
        "deleted_at": plant.deleted_at,
        "version": plant.version,
        "schedules": [
            _schedule_payload(
                schedule,
                action_type=action_types_by_id.get(schedule.action_type_id),
                task_completions=task_completions_by_schedule_id.get(schedule.id, []),
            )
            for schedule in schedules
        ],
    }


def get_user_plant_insight_payload(
    query: Any = "",
    limit: Any = 50,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    db, user_id, error = _context_or_error()
    if error is not None:
        return {"status": "error", "message": error}

    assert db is not None and user_id is not None
    normalized_query = _coerce_query(query)
    date_filter, date_filter_kind = _parse_query_date_filter(normalized_query, today=today)
    wants_missed_tasks = _asks_for_missed_tasks(normalized_query)
    bounded_limit = _coerce_limit(limit, default=50, maximum=100)
    plants = list(
        db.execute(
            select(Plant)
            .where(
                Plant.user_id == user_id,
                Plant.deleted_at.is_(None),
            )
            .order_by(Plant.updated_at.desc())
        ).scalars()
    )
    if _is_generic_plant_query(normalized_query):
        matched = plants
    else:
        matched = [
            plant
            for plant in plants
            if _matches_query(plant.name, plant.species, plant.note, plant.overview, query=normalized_query)
        ]
    visible = matched[:bounded_limit]
    visible_plant_ids = [plant.id for plant in visible]

    schedules_by_plant_id: dict[str, list[Schedule]] = {plant_id: [] for plant_id in visible_plant_ids}
    action_types_by_id: dict[str, ActionType] = {}
    task_completions_by_schedule_id: dict[str, list[TaskCompletion]] = {}
    missed_tasks: list[dict[str, Any]] = []
    completed_task_count = 0
    if visible_plant_ids:
        schedules = list(
            db.execute(
                select(Schedule)
                .where(
                    Schedule.user_id == user_id,
                    Schedule.plant_id.in_(visible_plant_ids),
                    Schedule.deleted_at.is_(None),
                )
                .order_by(Schedule.next_due_at.asc(), Schedule.updated_at.desc())
            ).scalars()
        )
        for schedule in schedules:
            schedules_by_plant_id.setdefault(schedule.plant_id, []).append(schedule)

        schedule_ids = [schedule.id for schedule in schedules]
        action_type_ids = sorted({schedule.action_type_id for schedule in schedules})
        if action_type_ids:
            action_types = list(
                db.execute(
                    select(ActionType).where(
                        ActionType.user_id == user_id,
                        ActionType.id.in_(action_type_ids),
                        ActionType.deleted_at.is_(None),
                    )
                ).scalars()
            )
            action_types_by_id = {item.id: item for item in action_types}

        if schedule_ids:
            task_completion_filters = [
                TaskCompletion.user_id == user_id,
                TaskCompletion.schedule_id.in_(schedule_ids),
                TaskCompletion.deleted_at.is_(None),
            ]
            if date_filter is not None:
                task_completion_filters.append(TaskCompletion.completion_date == date_filter)
            task_completions = list(
                db.execute(
                    select(TaskCompletion)
                    .where(*task_completion_filters)
                    .order_by(TaskCompletion.completion_date.desc(), TaskCompletion.created_at.desc())
                ).scalars()
            )
            completed_schedule_ids_for_date = {
                task_completion.schedule_id
                for task_completion in task_completions
                if date_filter is not None and task_completion.completion_date == date_filter
            }
            completed_task_count = (
                len(completed_schedule_ids_for_date) if date_filter is not None else len(task_completions)
            )
            for task_completion in task_completions:
                task_completions_by_schedule_id.setdefault(
                    task_completion.schedule_id,
                    [],
                ).append(task_completion)
            if wants_missed_tasks and date_filter is not None:
                visible_plants_by_id = {plant.id: plant for plant in visible}
                for schedule in schedules:
                    if schedule.id in completed_schedule_ids_for_date:
                        continue
                    if not _schedule_due_on(schedule, date_filter):
                        continue
                    plant = visible_plants_by_id.get(schedule.plant_id)
                    if plant is None:
                        continue
                    missed_tasks.append(
                        _missed_task_payload(
                            plant=plant,
                            schedule=schedule,
                            action_type=action_types_by_id.get(schedule.action_type_id),
                            target_date=date_filter,
                        )
                    )

    payload: dict[str, Any] = {
        "status": "ok",
        "kind": "plants",
        "total_count": len(plants),
        "matched_count": len(matched),
        "returned_count": len(visible),
        "items": [
            _plant_payload(
                plant,
                schedules=schedules_by_plant_id.get(plant.id, []),
                action_types_by_id=action_types_by_id,
                task_completions_by_schedule_id=task_completions_by_schedule_id,
            )
            for plant in visible
        ],
    }
    if date_filter is not None:
        payload["date_filter"] = {
            "kind": date_filter_kind,
            "date": date_filter,
        }
        payload["completed_task_count"] = completed_task_count
    if wants_missed_tasks and date_filter is not None:
        payload["missed_task_count"] = len(missed_tasks)
        payload["missed_tasks"] = missed_tasks
    return payload


def get_user_journal_insight_payload(query: Any = "", limit: Any = 8) -> dict[str, Any]:
    db, user_id, error = _context_or_error()
    if error is not None:
        return {"status": "error", "message": error}

    assert db is not None and user_id is not None
    normalized_query = _coerce_query(query)
    bounded_limit = _coerce_limit(limit, default=8, maximum=20)
    rows = list(
        db.execute(
            select(Note, Plant)
            .join(Plant, Note.plant_id == Plant.id)
            .where(
                Note.user_id == user_id,
                Note.deleted_at.is_(None),
                Plant.user_id == user_id,
                Plant.deleted_at.is_(None),
            )
            .order_by(Note.entry_date.desc(), Note.updated_at.desc())
        ).all()
    )
    if _is_generic_journal_query(normalized_query):
        matched = rows
    else:
        matched = [
            (note, plant)
            for note, plant in rows
            if _matches_query(
                note.content,
                ",".join(note.tags),
                plant.name,
                plant.species,
                query=normalized_query,
            )
        ]
    visible = matched[:bounded_limit]
    return {
        "status": "ok",
        "kind": "journal",
        "total_count": len(rows),
        "matched_count": len(matched),
        "items": [
            {
                "id": note.id,
                "plant_id": note.plant_id,
                "plant_name": plant.name,
                "plant_species": plant.species,
                "entry_date": note.entry_date,
                "content": note.content,
                "tags": note.tags,
                "image_count": len(note.image_paths or []),
                "updated_at": note.updated_at,
            }
            for note, plant in visible
        ],
    }


def dump_tool_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=_json_default, ensure_ascii=False)


@tool("users_plant_insight_tool")
def users_plant_insight_tool(query: Any = "", limit: Any = 50) -> str:
    """Use only when the user asks about plants saved in their own Plant Reminder account, including all plant table fields, schedules, task completions, plant list, names, species, care fields, notes stored on the plant profile, paused status, or saved plant details. Do not use for journal/note/log/history questions."""
    return dump_tool_payload(get_user_plant_insight_payload(query=query, limit=limit))


@tool("users_journal_insight_tool")
def users_journal_insight_tool(query: Any = "", limit: Any = 8) -> str:
    """Use only when the user asks about their own plant journal entries, notes, logs, observations, symptoms over time, progress history, or what they recorded. Do not use for general saved plant profile or care-field questions unless the user explicitly asks from journal history."""
    return dump_tool_payload(get_user_journal_insight_payload(query=query, limit=limit))


@tool("manage_plant_schedules_tool")
def manage_plant_schedules_tool(
    action: str,
    plant_name: str,
    action_type_name: str | None = None,
    frequency_type: str | None = None,
    frequency_days: int | None = None,
    days_of_week: list[str] | None = None,
    scheduled_time: str | None = None,
    note: str | None = None,
    start_date: str | None = None,
    schedule_id: str | None = None,
) -> str:
    """Perform CRUD (Create, Read, Update, Delete) operations on scheduled tasks / care reminders for the user's plants.
    
    Arguments:
    - action: The CRUD action to perform. One of: "create", "read", "update", "delete".
    - plant_name: The name of the plant (e.g. "Peace Lily", "abc plant"). We will find the plant by this name. If the user doesn't own this plant, a friendly error message is returned.
    - action_type_name: The name of the action/task (e.g. "Water", "Fertilize", "Repot", "Prune"). Case-insensitive. Required for "create".
    - frequency_type: The frequency type. One of: "INTERVAL" (for repeating every X days) or "SPECIFIC_DAYS" (for specific days of the week). Defaults to "INTERVAL" if not specified.
    - frequency_days: Number of days between tasks (e.g., 3 for every 3 days). Only used when frequency_type is "INTERVAL". Defaults to 7 for water, 14 for fertilize, 30 for prune, 365 for repot.
    - days_of_week: List of days of week (e.g. ["Monday", "Wednesday"]) when frequency_type is "SPECIFIC_DAYS".
    - scheduled_time: Time of day in 24-hour format "HH:MM" (e.g., "15:00" for 3 PM, "09:00" for 9 AM). Defaults to "09:00" if not specified.
    - note: Optional text note/instruction for this schedule.
    - start_date: Date to start the schedule in "YYYY-MM-DD" format. Defaults to today's date if not specified.
    - schedule_id: The ID of the schedule. Required for "update" and "delete" operations if multiple schedules exist, or to identify a specific schedule.
    """
    from datetime import time, timezone
    from sqlalchemy import func
    from app.api.v1.endpoints.common import bump_version, soft_delete

    db, user_id, error = _context_or_error()
    if error is not None:
        return dump_tool_payload({"status": "error", "message": error})

    assert db is not None and user_id is not None

    # Clean the query plant name
    clean_query_name = plant_name.strip().lower()
    # Strip common prefixes/suffixes like "my", "plant", "cây" to match robustly
    for word in ["my", "plant", "cây"]:
        if clean_query_name.startswith(word + " "):
            clean_query_name = clean_query_name[len(word)+1:].strip()
        if clean_query_name.endswith(" " + word):
            clean_query_name = clean_query_name[:-len(word)-1].strip()

    # Query all active plants of the user
    all_plants = list(db.execute(
        select(Plant).where(
            Plant.user_id == user_id,
            Plant.deleted_at.is_(None)
        )
    ).scalars())

    matched_plant = None
    # 1. Try exact match first
    for p in all_plants:
        if p.name.strip().lower() == plant_name.strip().lower():
            matched_plant = p
            break

    # 2. Try match against cleaned query name
    if not matched_plant:
        for p in all_plants:
            p_name_clean = p.name.strip().lower()
            if p_name_clean == clean_query_name:
                matched_plant = p
                break

    # 3. Try substring match
    if not matched_plant:
        for p in all_plants:
            p_name_clean = p.name.strip().lower()
            if clean_query_name in p_name_clean or p_name_clean in clean_query_name:
                matched_plant = p
                break

    # If plant is not found, return friendly error message (dont hardcode plant name)
    if not matched_plant:
        return dump_tool_payload({
            "status": "error",
            "message": f"I couldn't find a plant named '{plant_name}' in your library. Please make sure you have added it first."
        })

    act = action.strip().lower()

    if act == "create":
        if not action_type_name:
            return dump_tool_payload({"status": "error", "message": "action_type_name is required to create a schedule."})

        # Map action name to a standardized Title Case name
        clean_action = action_type_name.strip().lower()
        if "water" in clean_action or "tưới" in clean_action:
            display_name = "Watering"
            default_icon = "water_droplet"
            default_color = "#2196F3"
        elif "fertiliz" in clean_action or "bón phân" in clean_action:
            display_name = "Fertilize"
            default_icon = "fertilize"
            default_color = "#4CAF50"
        elif "repot" in clean_action or "thay chậu" in clean_action:
            display_name = "Repot"
            default_icon = "repot"
            default_color = "#8B4513"
        elif "prune" in clean_action or "trim" in clean_action or "cắt tỉa" in clean_action:
            display_name = "Prune"
            default_icon = "prune"
            default_color = "#FF9800"
        elif "mist" in clean_action or "phun sương" in clean_action:
            display_name = "Mist"
            default_icon = "mist"
            default_color = "#00BCD4"
        else:
            display_name = action_type_name.strip().capitalize()
            default_icon = "water_droplet"
            default_color = "#9C27B0"

        # Find or create ActionType
        action_type_stmt = select(ActionType).where(
            ActionType.user_id == user_id,
            ActionType.deleted_at.is_(None),
            func.lower(ActionType.name) == display_name.lower()
        )
        action_type = db.execute(action_type_stmt).scalar_one_or_none()

        if not action_type:
            action_type = ActionType(
                user_id=user_id,
                name=display_name,
                icon=default_icon,
                color=default_color
            )
            db.add(action_type)
            db.flush()

        # Parse schedule configurations
        freq_type = (frequency_type or "INTERVAL").upper()
        freq_days = frequency_days
        if freq_type == "INTERVAL" and freq_days is None:
            # Smart defaults based on task type
            if "water" in display_name.lower():
                freq_days = 7
            elif "fertiliz" in display_name.lower():
                freq_days = 14
            elif "repot" in display_name.lower():
                freq_days = 365
            elif "prune" in display_name.lower():
                freq_days = 30
            else:
                freq_days = 7

        parsed_time = time(9, 0)
        if scheduled_time:
            time_match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", scheduled_time.strip())
            if time_match:
                hours = int(time_match.group(1))
                minutes = int(time_match.group(2))
                seconds = int(time_match.group(3)) if time_match.group(3) else 0
                parsed_time = time(hours, minutes, seconds)

        # Resolve user's local date
        from app.agent_tools.user_insights import _user_local_time, _user_timezone
        user_date = None
        local_time_val = _user_local_time.get()
        timezone_val = _user_timezone.get()

        if local_time_val:
            try:
                dt = datetime.fromisoformat(local_time_val.replace(" ", "T"))
                user_date = dt.date()
            except Exception:
                pass

        if not user_date and timezone_val:
            try:
                tz = _timezone_from_context(timezone_val)
                user_date = datetime.now(tz).date()
            except Exception:
                pass

        if not user_date:
            user_date = date.today()

        parsed_start_date = user_date
        if start_date:
            try:
                parsed_start_date = date.fromisoformat(start_date.strip())
            except ValueError:
                pass

        next_due_datetime = _local_schedule_datetime_as_utc(parsed_start_date, parsed_time)

        schedule = Schedule(
            user_id=user_id,
            plant_id=matched_plant.id,
            action_type_id=action_type.id,
            frequency_type=freq_type,
            frequency_days=freq_days,
            days_of_week=days_of_week,
            scheduled_time=parsed_time,
            note=note,
            start_date=parsed_start_date,
            next_due_at=next_due_datetime
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        _last_interacted_schedule_id.set(schedule.id)

        return dump_tool_payload({
            "status": "ok",
            "message": f"Successfully created {display_name} reminder for '{matched_plant.name}' starting {parsed_start_date} at {parsed_time}.",
            "schedule_id": schedule.id,
            "plant_name": matched_plant.name
        })

    elif act == "read":
        schedules_stmt = select(Schedule).where(
            Schedule.user_id == user_id,
            Schedule.plant_id == matched_plant.id,
            Schedule.deleted_at.is_(None)
        ).order_by(Schedule.next_due_at.asc())
        schedules = list(db.execute(schedules_stmt).scalars())

        items = []
        for s in schedules:
            act_type = db.execute(select(ActionType).where(ActionType.id == s.action_type_id)).scalar_one_or_none()
            items.append({
                "id": s.id,
                "action_type_name": act_type.name if act_type else "Unknown",
                "frequency_type": s.frequency_type,
                "frequency_days": s.frequency_days,
                "days_of_week": s.days_of_week,
                "scheduled_time": str(s.scheduled_time),
                "next_due_at": s.next_due_at,
                "note": s.note
            })

        if items:
            _last_interacted_schedule_id.set(items[0]["id"])

        return dump_tool_payload({
            "status": "ok",
            "plant_name": matched_plant.name,
            "schedules": items
        })

    elif act == "update":
        schedule = None
        if schedule_id:
            schedule = db.execute(
                select(Schedule).where(
                    Schedule.id == schedule_id,
                    Schedule.user_id == user_id,
                    Schedule.deleted_at.is_(None)
                )
            ).scalar_one_or_none()
        else:
            if action_type_name:
                # Find matching action type
                act_stmt = select(ActionType).where(
                    ActionType.user_id == user_id,
                    ActionType.deleted_at.is_(None),
                    func.lower(ActionType.name) == action_type_name.strip().lower()
                )
                action_type = db.execute(act_stmt).scalar_one_or_none()
                if action_type:
                    schedule = db.execute(
                        select(Schedule).where(
                            Schedule.plant_id == matched_plant.id,
                            Schedule.action_type_id == action_type.id,
                            Schedule.deleted_at.is_(None)
                        )
                    ).scalar_one_or_none()

            if not schedule:
                schedules = list(db.execute(
                    select(Schedule).where(
                        Schedule.plant_id == matched_plant.id,
                        Schedule.deleted_at.is_(None)
                    )
                ).scalars())
                if len(schedules) == 1:
                    schedule = schedules[0]
                elif len(schedules) > 1:
                    return dump_tool_payload({
                        "status": "ambiguous",
                        "message": f"Multiple schedules found for '{matched_plant.name}'. Please specify which one to update.",
                        "items": [
                            {
                                "id": s.id,
                                "action_type": db.execute(select(ActionType.name).where(ActionType.id == s.action_type_id)).scalar(),
                                "scheduled_time": str(s.scheduled_time)
                            }
                            for s in schedules
                        ]
                    })

        if not schedule:
            return dump_tool_payload({"status": "error", "message": f"No schedule found to update for plant '{matched_plant.name}'."})

        # Apply updates
        if frequency_type:
            schedule.frequency_type = frequency_type.upper()
        if frequency_days is not None:
            schedule.frequency_days = frequency_days
        if days_of_week is not None:
            schedule.days_of_week = days_of_week
        if scheduled_time:
            time_match = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", scheduled_time.strip())
            if time_match:
                hours = int(time_match.group(1))
                minutes = int(time_match.group(2))
                seconds = int(time_match.group(3)) if time_match.group(3) else 0
                schedule.scheduled_time = time(hours, minutes, seconds)
        if note is not None:
            schedule.note = note
        if start_date:
            try:
                schedule.start_date = date.fromisoformat(start_date.strip())
            except ValueError:
                pass

        # Recalculate next_due_at
        ref_date = schedule.start_date or date.today()
        ref_time = schedule.scheduled_time or time(9, 0)
        schedule.next_due_at = _local_schedule_datetime_as_utc(ref_date, ref_time)

        bump_version(schedule)
        db.commit()
        db.refresh(schedule)

        _last_interacted_schedule_id.set(schedule.id)

        return dump_tool_payload({
            "status": "ok",
            "message": f"Successfully updated schedule for '{matched_plant.name}'.",
            "schedule_id": schedule.id,
            "plant_name": matched_plant.name
        })

    elif act == "delete":
        schedule = None
        if schedule_id:
            schedule = db.execute(
                select(Schedule).where(
                    Schedule.id == schedule_id,
                    Schedule.user_id == user_id,
                    Schedule.deleted_at.is_(None)
                )
            ).scalar_one_or_none()
        else:
            if action_type_name:
                act_stmt = select(ActionType).where(
                    ActionType.user_id == user_id,
                    ActionType.deleted_at.is_(None),
                    func.lower(ActionType.name) == action_type_name.strip().lower()
                )
                action_type = db.execute(act_stmt).scalar_one_or_none()
                if action_type:
                    schedule = db.execute(
                        select(Schedule).where(
                            Schedule.plant_id == matched_plant.id,
                            Schedule.action_type_id == action_type.id,
                            Schedule.deleted_at.is_(None)
                        )
                    ).scalar_one_or_none()

            if not schedule:
                schedules = list(db.execute(
                    select(Schedule).where(
                        Schedule.plant_id == matched_plant.id,
                        Schedule.deleted_at.is_(None)
                    )
                ).scalars())
                if len(schedules) == 1:
                    schedule = schedules[0]
                elif len(schedules) > 1:
                    return dump_tool_payload({
                        "status": "ambiguous",
                        "message": f"Multiple schedules found for '{matched_plant.name}'. Please specify which one to delete.",
                        "items": [
                            {
                                "id": s.id,
                                "action_type": db.execute(select(ActionType.name).where(ActionType.id == s.action_type_id)).scalar(),
                                "scheduled_time": str(s.scheduled_time)
                            }
                            for s in schedules
                        ]
                    })

        if not schedule:
            return dump_tool_payload({"status": "error", "message": f"No schedule found to delete for plant '{matched_plant.name}'."})

        soft_delete(schedule)
        db.commit()

        _last_interacted_schedule_id.set(schedule.id)

        return dump_tool_payload({
            "status": "ok",
            "message": f"Successfully deleted schedule for '{matched_plant.name}'.",
            "schedule_id": schedule.id,
            "plant_name": matched_plant.name
        })

    else:
        return dump_tool_payload({"status": "error", "message": f"Unsupported action '{action}'."})
