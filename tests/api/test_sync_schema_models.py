from app.db.base import Base


def test_sync_tables_exist_in_metadata() -> None:
    expected_tables = {
        "action_types",
        "plants",
        "profile_settings",
        "schedules",
        "task_completions",
        "notes",
    }
    assert expected_tables.issubset(set(Base.metadata.tables.keys()))


def test_sync_columns_exist_for_core_resources() -> None:
    sync_columns = {"created_at", "updated_at", "deleted_at", "version"}
    for table_name in ["action_types", "plants", "schedules", "task_completions", "notes"]:
        columns = set(Base.metadata.tables[table_name].columns.keys())
        assert sync_columns.issubset(columns)
