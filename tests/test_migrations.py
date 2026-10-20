"""Migration checks for the controller database."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[1]


def test_initial_migration_creates_controller_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "migrated.sqlite3"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "python/lab_api/migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        names = set(inspect(engine).get_table_names())
        assert "alembic_version" in names
        assert "workers" in names
        assert "experiments" in names
        assert "worker_commands" in names
        assert "optimizer_requests" in names
        assert "job_events" in names
        assert len(names) == 20
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version
    finally:
        engine.dispose()
