import asyncio
from typing import cast

from sqlalchemy import Table
from sqlalchemy.engine import Connection, make_url

from agroclimate.db.models import Field, User, WeatherForecast
from agroclimate.db.session import create_engine
from agroclimate.db.settings import get_database_settings


def create_external_tables(connection: Connection) -> None:
    tables = (
        cast(Table, User.__table__),
        cast(Table, Field.__table__),
        cast(Table, WeatherForecast.__table__),
    )
    for table in tables:
        table.create(connection, checkfirst=True)


async def main() -> None:
    settings = get_database_settings()
    if make_url(settings.database_url).host not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RuntimeError(
            "Local external tables can only be created in local PostgreSQL"
        )

    engine = create_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(create_external_tables)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
