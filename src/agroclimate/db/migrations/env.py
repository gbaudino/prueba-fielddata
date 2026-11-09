import asyncio
from logging.config import fileConfig
from typing import Literal

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import SchemaItem

from agroclimate.db import models as _models  # noqa: F401
from agroclimate.db.base import Base
from agroclimate.db.settings import get_database_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = Base.metadata
EXTERNAL_TABLES = frozenset({"users", "fields", "weather_forecasts"})


def include_object(
    object_: SchemaItem,
    name: str | None,
    type_: Literal[
        "schema",
        "table",
        "column",
        "index",
        "unique_constraint",
        "foreign_key_constraint",
        "check_constraint",
    ],
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    return not (type_ == "table" and name in EXTERNAL_TABLES)


def get_database_url() -> str:
    return get_database_settings().database_url.render_as_string(
        hide_password=False
    )


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(
        get_database_url(),
        poolclass=pool.NullPool,
    )

    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
