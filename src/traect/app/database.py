from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from traect.db.base import Base
from traect.domain import models as _models  # noqa: F401

MIGRATIONS_ROOT = Path(__file__).resolve().parents[3] / "migrations"
APP_TABLES = {"workspace", "domain", "week", "week_domain_state"}


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        if ":memory:" in database_url:
            return create_engine(
                database_url,
                future=True,
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
        return create_engine(database_url, future=True, poolclass=NullPool)
    return create_engine(database_url, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, future=True)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def migrate_schema(engine: Engine) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_ROOT))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def adopt_legacy_schema(connection: Connection) -> None:
    legacy_revision = detect_legacy_revision(connection)
    if legacy_revision is None:
        return
    version_table = Table(
        "alembic_version",
        MetaData(),
        Column("version_num", String(32), primary_key=True, nullable=False),
    )
    version_table.create(connection, checkfirst=True)
    connection.execute(version_table.insert().values(version_num=legacy_revision))


def detect_legacy_revision(connection: Connection) -> str | None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "alembic_version" in tables:
        versions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        if versions:
            if versions == ["0008_minimum_acceptable_level"]:
                return None
            raise RuntimeError(
                "database uses a Traect migration revision that predates the squashed baseline; "
                "upgrade it with the previous release before deploying this version"
            )

    existing_app_tables = tables & APP_TABLES
    if not existing_app_tables:
        return None
    if existing_app_tables != APP_TABLES:
        raise RuntimeError("database contains an incomplete legacy traect schema; migration cannot continue safely")

    domain_columns = {column["name"] for column in inspector.get_columns("domain")}
    week_columns = {column["name"] for column in inspector.get_columns("week")}
    state_columns = {column["name"] for column in inspector.get_columns("week_domain_state")}
    index_names = {index["name"] for index in inspector.get_indexes("domain")}

    is_squashed_schema = (
        {"sort_order", "archived_at", "minimum_acceptable_level"} <= domain_columns
        and {
            "sacrificed_domain_id",
            "sacrificed_domain_name",
            "corrected_at",
            "correction_note",
            "revision",
        }
        <= week_columns
        and {
            "domain_name",
            "attention",
            "condition",
            "minimum_acceptable_level_snapshot",
        }
        <= state_columns
        and {"focus_domain_id", "focus_domain_name"}.isdisjoint(week_columns)
        and "uq_domain_workspace_active_name" in index_names
    )
    if is_squashed_schema:
        return "0008_minimum_acceptable_level"

    raise RuntimeError(
        "database schema predates the squashed Traect migration baseline; "
        "upgrade it with the previous release before deploying this version"
    )
