from datetime import date, datetime, time, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_tools.user_insights import (
    _user_timezone,
    get_user_plant_insight_payload,
    manage_plant_schedules_tool,
    reset_user_insight_context,
    set_user_insight_context,
    users_plant_insight_tool,
)
from app.models.action_type import ActionType
from app.models.base import Base
from app.models.plant import Plant
from app.models.schedule import Schedule
from app.models.task_completion import TaskCompletion


def test_generic_plants_query_returns_all_owned_plants() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)
    db = session_factory()
    try:
        user_id = "user-1"
        other_user_id = "user-2"
        db.add_all(
            [
                Plant(user_id=user_id, name="Pothos", species="Epipremnum aureum"),
                Plant(user_id=user_id, name="Snake Plant", species="Dracaena trifasciata"),
                Plant(user_id=other_user_id, name="Other Cactus", species="Mammillaria"),
            ]
        )
        db.commit()

        db_token, user_id_token = set_user_insight_context(db, user_id)
        try:
            payload = get_user_plant_insight_payload(query="plants")
        finally:
            reset_user_insight_context(db_token, user_id_token)

        names = {item["name"] for item in payload["items"]}
        assert payload["total_count"] == 2
        assert payload["matched_count"] == 2
        assert names == {"Pothos", "Snake Plant"}
    finally:
        db.close()


def test_plant_insight_tool_accepts_loose_llm_arguments() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)
    db = session_factory()
    try:
        user_id = "user-1"
        db.add_all(
            [
                Plant(user_id=user_id, name="Pothos", species="Epipremnum aureum"),
                Plant(user_id=user_id, name="Snake Plant", species="Dracaena trifasciata"),
            ]
        )
        db.commit()

        db_token, user_id_token = set_user_insight_context(db, user_id)
        try:
            all_limit_payload = users_plant_insight_tool.invoke(
                {"query": "plants", "limit": "all"}
            )
            null_arg_payload = users_plant_insight_tool.invoke({"query": None, "limit": None})
        finally:
            reset_user_insight_context(db_token, user_id_token)

        assert '"matched_count": 2' in all_limit_payload
        assert '"matched_count": 2' in null_arg_payload
    finally:
        db.close()


def test_plant_insight_includes_schedules_and_task_completions() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)
    db = session_factory()
    try:
        user_id = "user-1"
        plant = Plant(
            user_id=user_id,
            name="Pothos",
            species="Epipremnum aureum",
            potted_date=date(2026, 1, 1),
            image_path="/uploads/pothos.jpg",
            note="Kitchen shelf.",
            is_paused=False,
            overview="Trailing houseplant.",
            water="Water when top soil dries.",
            sunlight="Bright indirect light.",
            fertilizer="Monthly in growing season.",
            propagating="Stem cuttings.",
            varieties="Golden pothos",
            humidity="Average home humidity.",
            temperature="18-29C",
            soil="Well-draining mix.",
            running="Fast trailing growth.",
            potting_and_repotting="Repot in spring.",
            pests_and_diseases="Watch for mealybugs.",
            toxicity="Toxic to pets.",
            propagation="Cut below a node.",
        )
        action_type = ActionType(user_id=user_id, name="Water", icon="water", color="#00AEEF")
        db.add_all([plant, action_type])
        db.commit()
        db.refresh(plant)
        db.refresh(action_type)

        schedule = Schedule(
            user_id=user_id,
            plant_id=plant.id,
            action_type_id=action_type.id,
            frequency_type="INTERVAL",
            frequency_days=3,
            days_of_week=None,
            scheduled_time=time(9, 0),
            note="Morning water",
            last_completed_at=datetime(2026, 6, 17, 9, 0, tzinfo=timezone.utc),
            next_due_at=datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc),
            start_date=date(2026, 6, 1),
        )
        db.add(schedule)
        db.commit()
        db.refresh(schedule)

        task_completion = TaskCompletion(
            user_id=user_id,
            schedule_id=schedule.id,
            completion_date=date(2026, 6, 17),
            completed_at=datetime(2026, 6, 17, 9, 5, tzinfo=timezone.utc),
        )
        db.add(task_completion)
        db.commit()
        db.refresh(task_completion)

        db_token, user_id_token = set_user_insight_context(db, user_id)
        try:
            payload = get_user_plant_insight_payload(query="pothos")
        finally:
            reset_user_insight_context(db_token, user_id_token)

        assert payload["matched_count"] == 1
        item = payload["items"][0]
        assert item["id"] == plant.id
        assert item["user_id"] == user_id
        assert item["image_path"] == "/uploads/pothos.jpg"
        assert item["propagation"] == "Cut below a node."
        assert item["version"] == 1

        assert len(item["schedules"]) == 1
        schedule_payload = item["schedules"][0]
        assert schedule_payload["id"] == schedule.id
        assert schedule_payload["plant_id"] == plant.id
        assert schedule_payload["action_type_id"] == action_type.id
        assert schedule_payload["action_type"]["name"] == "Water"
        assert schedule_payload["frequency_type"] == "INTERVAL"
        assert schedule_payload["frequency_days"] == 3
        assert schedule_payload["scheduled_time"] == time(9, 0)
        assert schedule_payload["note"] == "Morning water"

        assert len(schedule_payload["task_completions"]) == 1
        completion_payload = schedule_payload["task_completions"][0]
        assert completion_payload["id"] == task_completion.id
        assert completion_payload["schedule_id"] == schedule.id
        assert completion_payload["completion_date"] == date(2026, 6, 17)
        assert completion_payload["version"] == 1
    finally:
        db.close()


def test_plant_insight_parses_yesterday_and_reports_missed_tasks() -> None:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)
    db = session_factory()
    try:
        user_id = "user-1"
        action_type = ActionType(user_id=user_id, name="Water", icon="water", color="#00AEEF")
        missed_plant = Plant(user_id=user_id, name="Pothos", species="Epipremnum aureum")
        completed_plant = Plant(user_id=user_id, name="Snake Plant", species="Dracaena trifasciata")
        db.add_all([action_type, missed_plant, completed_plant])
        db.commit()
        db.refresh(action_type)
        db.refresh(missed_plant)
        db.refresh(completed_plant)

        yesterday = date(2026, 6, 17)
        missed_schedule = Schedule(
            user_id=user_id,
            plant_id=missed_plant.id,
            action_type_id=action_type.id,
            frequency_type="INTERVAL",
            frequency_days=1,
            scheduled_time=time(9, 0),
            start_date=yesterday,
        )
        completed_schedule = Schedule(
            user_id=user_id,
            plant_id=completed_plant.id,
            action_type_id=action_type.id,
            frequency_type="INTERVAL",
            frequency_days=1,
            scheduled_time=time(10, 0),
            start_date=yesterday,
        )
        db.add_all([missed_schedule, completed_schedule])
        db.commit()
        db.refresh(missed_schedule)
        db.refresh(completed_schedule)

        older_completion = TaskCompletion(
            user_id=user_id,
            schedule_id=missed_schedule.id,
            completion_date=date(2026, 6, 16),
            completed_at=datetime(2026, 6, 16, 9, 5, tzinfo=timezone.utc),
        )
        yesterday_completion = TaskCompletion(
            user_id=user_id,
            schedule_id=completed_schedule.id,
            completion_date=yesterday,
            completed_at=datetime(2026, 6, 17, 10, 5, tzinfo=timezone.utc),
        )
        db.add_all([older_completion, yesterday_completion])
        db.commit()

        db_token, user_id_token = set_user_insight_context(db, user_id)
        try:
            payload = get_user_plant_insight_payload(
                query="tell me all task that i missed yesterday",
                today=date(2026, 6, 18),
            )
        finally:
            reset_user_insight_context(db_token, user_id_token)

        assert payload["date_filter"]["kind"] == "yesterday"
        assert payload["date_filter"]["date"] == yesterday
        assert payload["completed_task_count"] == 1
        assert payload["missed_task_count"] == 1
        assert payload["missed_tasks"][0]["plant_name"] == "Pothos"

        completions_by_schedule = {
            schedule["id"]: schedule["task_completions"]
            for item in payload["items"]
            for schedule in item["schedules"]
        }
        assert completions_by_schedule[missed_schedule.id] == []
        assert len(completions_by_schedule[completed_schedule.id]) == 1
        assert completions_by_schedule[completed_schedule.id][0]["completion_date"] == yesterday
    finally:
        db.close()


def test_manage_plant_schedules_tool_crud() -> None:
    import json

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)
    db = session_factory()
    try:
        user_id = "user-1"
        plant = Plant(user_id=user_id, name="My Rose", species="Rosa")
        db.add(plant)
        db.commit()
        db.refresh(plant)

        db_token, user_id_token = set_user_insight_context(db, user_id)
        timezone_token = _user_timezone.set("GMT+07:00")
        try:
            # 1. Create schedule on plant
            create_res = manage_plant_schedules_tool.invoke({
                "action": "create",
                "plant_name": "My Rose",
                "action_type_name": "water",
                "frequency_type": "INTERVAL",
                "frequency_days": 3,
                "scheduled_time": "09:30",
                "start_date": "2026-06-26",
                "note": "Water in afternoon"
            })
            create_payload = json.loads(create_res)
            assert create_payload["status"] == "ok"
            assert "Successfully" in create_payload["message"]
            assert create_payload["plant_name"] == "My Rose"
            sched_id = create_payload["schedule_id"]

            # Verify schedule is in db and ActionType is created
            schedule = db.execute(select(Schedule).where(Schedule.id == sched_id)).scalar_one_or_none()
            assert schedule is not None
            assert schedule.frequency_days == 3
            assert schedule.scheduled_time == time(9, 30)
            assert schedule.start_date == date(2026, 6, 26)
            assert schedule.next_due_at == datetime(2026, 6, 26, 2, 30)
            assert schedule.note == "Water in afternoon"

            action_type = db.execute(select(ActionType).where(ActionType.id == schedule.action_type_id)).scalar_one_or_none()
            assert action_type is not None
            assert action_type.name == "Watering"
            assert action_type.icon == "water_droplet"
            assert action_type.color == "#2196F3"

            # 2. Create schedule on non-existent plant (assert friendly message, not hardcoded)
            fail_res = manage_plant_schedules_tool.invoke({
                "action": "create",
                "plant_name": "Nonexistent Orchid",
                "action_type_name": "fertilize"
            })
            fail_payload = json.loads(fail_res)
            assert fail_payload["status"] == "error"
            assert "Nonexistent Orchid" in fail_payload["message"]
            assert "couldn't find" in fail_payload["message"] or "cannot find" in fail_payload["message"].lower()

            # 3. Read schedules
            read_res = manage_plant_schedules_tool.invoke({
                "action": "read",
                "plant_name": "My Rose"
            })
            read_payload = json.loads(read_res)
            assert read_payload["status"] == "ok"
            assert len(read_payload["schedules"]) == 1
            assert read_payload["schedules"][0]["id"] == sched_id

            # 4. Update schedule
            update_res = manage_plant_schedules_tool.invoke({
                "action": "update",
                "plant_name": "My Rose",
                "schedule_id": sched_id,
                "frequency_days": 5,
                "scheduled_time": "10:45",
                "start_date": "2026-06-27",
            })
            update_payload = json.loads(update_res)
            assert update_payload["status"] == "ok"
            
            db.expire(schedule)
            schedule = db.execute(select(Schedule).where(Schedule.id == sched_id)).scalar_one_or_none()
            assert schedule.frequency_days == 5
            assert schedule.scheduled_time == time(10, 45)
            assert schedule.start_date == date(2026, 6, 27)
            assert schedule.next_due_at == datetime(2026, 6, 27, 3, 45)

            # 5. Delete schedule
            delete_res = manage_plant_schedules_tool.invoke({
                "action": "delete",
                "plant_name": "My Rose",
                "schedule_id": sched_id
            })
            delete_payload = json.loads(delete_res)
            assert delete_payload["status"] == "ok"

            db.expire(schedule)
            schedule = db.execute(select(Schedule).where(Schedule.id == sched_id)).scalar_one_or_none()
            assert schedule.deleted_at is not None
        finally:
            _user_timezone.reset(timezone_token)
            reset_user_insight_context(db_token, user_id_token)
    finally:
        db.close()


def test_manage_plant_schedules_tool_supports_iana_timezone_for_next_due_at() -> None:
    import json

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)
    db = session_factory()
    try:
        user_id = "user-1"
        plant = Plant(user_id=user_id, name="Thai Basil", species="Ocimum basilicum")
        db.add(plant)
        db.commit()

        db_token, user_id_token = set_user_insight_context(db, user_id)
        timezone_token = _user_timezone.set("Asia/Bangkok")
        try:
            create_res = manage_plant_schedules_tool.invoke({
                "action": "create",
                "plant_name": "Thai Basil",
                "action_type_name": "water",
                "scheduled_time": "09:30",
                "start_date": "2026-06-26",
            })
            create_payload = json.loads(create_res)
            assert create_payload["status"] == "ok"

            schedule = db.execute(
                select(Schedule).where(Schedule.id == create_payload["schedule_id"])
            ).scalar_one()
            assert schedule.next_due_at == datetime(2026, 6, 26, 2, 30)
        finally:
            _user_timezone.reset(timezone_token)
            reset_user_insight_context(db_token, user_id_token)
    finally:
        db.close()
