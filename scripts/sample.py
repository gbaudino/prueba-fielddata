import asyncio
from collections import defaultdict
from datetime import date

from sqlalchemy import select

from agroclimate.db.models import EventType, Field, User, WeatherForecast
from agroclimate.db.session import create_engine, create_session_factory
from agroclimate.db.settings import get_database_settings


async def main() -> int:
    engine = create_engine(get_database_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            field = await session.scalar(
                select(Field)
                .where(Field.id.in_(select(WeatherForecast.field_id)))
                .order_by(Field.name)
                .limit(1)
            )
            if field is None:
                print("No hay datos. Corre `make seed` primero.")
                return 1

            forecasts = (
                await session.scalars(
                    select(WeatherForecast)
                    .where(WeatherForecast.field_id == field.id)
                    .order_by(WeatherForecast.forecast_date)
                )
            ).all()

            user_id = field.related_users[0]
            user_name = await session.scalar(
                select(User.name).where(User.id == user_id)
            )
    finally:
        await engine.dispose()

    by_date: dict[date, dict[EventType, int]] = defaultdict(dict)
    for forecast in forecasts:
        by_date[forecast.forecast_date][forecast.event_type] = (
            forecast.probability
        )

    events = list(EventType)
    top = max(forecasts, key=lambda forecast: forecast.probability)

    print(f"Usuario: {user_name} ({user_id})")
    print(f"Campo:   {field.name} ({field.id})")
    print()
    print("Pronosticos (probabilidad %):")
    print("  fecha       " + "".join(f"{e.value:>13}" for e in events))
    for day, probabilities in by_date.items():
        values = "".join(f"{probabilities.get(e, '-'):>13}" for e in events)
        print(f"  {day}  {values}")
    print()
    print("Ejemplo de alerta:")
    print(
        f"  curl -X POST http://localhost:8000/v1/alerts \\\n"
        f'    -H "X-User-Id: {user_id}" \\\n'
        '    -H "Content-Type: application/json" \\\n'
        f'    -d \'{{"field_id": "{field.id}", '
        f'"event_type": "{top.event_type.value}", '
        f'"threshold": {top.probability}}}\''
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
