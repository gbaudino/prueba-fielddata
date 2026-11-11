import asyncio
import subprocess
from typing import Any

import httpx2
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncEngine

from agroclimate.db.session import create_engine
from agroclimate.db.settings import get_database_settings

API_URL = "http://localhost:8000"
THRESHOLD = 80

FIND_TARGET = text(
    """
    select
        f.id as field_id,
        u.id as user_id,
        wf.event_type,
        count(*) as matches
    from fields f
    join users u on u.id = any(f.related_users)
    join weather_forecasts wf on wf.field_id = f.id
    where wf.probability >= :threshold
      and wf.forecast_date >= (now() at time zone f.timezone)::date
      and not exists (
          select 1
          from alerts a
          where a.field_id = f.id
            and a.event_type = wf.event_type
      )
    group by f.id, u.id, wf.event_type
    order by matches desc, f.id
    limit 1
    """
)

COUNT_OUTBOX = text(
    """
    select count(*)
    from outbox_events
    where event_type = 'notification.created'
      and payload->>'alert_id' = :alert_id
    """
)


def say(message: str = "") -> None:
    print(message, flush=True)


def run_worker() -> None:
    subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "--no-deps",
            "worker",
            "python",
            "-m",
            "agroclimate.worker",
            "--once",
        ],
        check=True,
    )


async def wait_for_api(client: httpx2.AsyncClient) -> bool:
    for _ in range(30):
        try:
            response = await client.get("/health/ready")
            if response.status_code == 200:
                return True
        except httpx2.HTTPError:
            pass
        await asyncio.sleep(1)
    return False


async def find_target(engine: AsyncEngine) -> Row[Any] | None:
    async with engine.connect() as connection:
        result = await connection.execute(
            FIND_TARGET,
            {"threshold": THRESHOLD},
        )
        return result.first()


async def count_outbox(engine: AsyncEngine, alert_id: str) -> int:
    async with engine.connect() as connection:
        result = await connection.scalar(
            COUNT_OUTBOX,
            {"alert_id": alert_id},
        )
        return int(result or 0)


async def list_notifications(
    client: httpx2.AsyncClient,
    headers: dict[str, str],
    field_id: str,
    alert_id: str,
) -> list[dict[str, Any]]:
    response = await client.get(
        "/v1/notifications",
        headers=headers,
        params={"field_id": field_id, "limit": 100},
    )
    response.raise_for_status()
    return [
        item
        for item in response.json()["items"]
        if item["alert_id"] == alert_id
    ]


async def main() -> int:
    say("Demo de alertas climaticas")
    engine = create_engine(get_database_settings().database_url)
    try:
        say("\n[1] Buscando un campo con pronosticos sobre el umbral")
        target = await find_target(engine)
        if target is None:
            say("No hay un campo libre para el demo. Proba `make reset`.")
            return 1

        field_id = str(target.field_id)
        headers = {"X-User-Id": str(target.user_id)}
        say(f"    campo:  {field_id}")
        say(f"    evento: {target.event_type}")
        say(f"    fechas con probabilidad >= {THRESHOLD}: {target.matches}")

        async with httpx2.AsyncClient(
            base_url=API_URL,
            timeout=15,
        ) as client:
            if not await wait_for_api(client):
                say("La API no esta corriendo. Ejecuta `make start` primero.")
                return 1

            say("\n[2] Creando la alerta por HTTP")
            created = await client.post(
                "/v1/alerts",
                headers=headers,
                json={
                    "field_id": field_id,
                    "event_type": target.event_type,
                    "threshold": THRESHOLD,
                },
            )
            if created.status_code != 201:
                say(f"    fallo: {created.status_code} {created.text}")
                return 1
            alert_id = created.json()["id"]
            say(f"    POST /v1/alerts -> 201 ({alert_id})")

            say("\n[3] Corriendo el worker")
            run_worker()
            first = await list_notifications(
                client, headers, field_id, alert_id
            )
            outbox = await count_outbox(engine, alert_id)
            say(f"    notificaciones de este usuario: {len(first)}")
            say(f"    eventos en el outbox (todos los usuarios): {outbox}")
            for item in sorted(first, key=lambda n: n["forecast_date"]):
                say(
                    f"    {item['forecast_date']}  "
                    f"probabilidad={item['probability']}  "
                    f"umbral={item['threshold']}"
                )
            if not first or outbox < len(first):
                say("    el worker no genero lo esperado")
                return 1

            say("\n[4] Corriendo el worker otra vez, sin cambios")
            run_worker()
            second = await list_notifications(
                client, headers, field_id, alert_id
            )
            if len(second) != len(first) or (
                await count_outbox(engine, alert_id) != outbox
            ):
                say("    la segunda pasada duplico datos")
                return 1
            say("    sin duplicados")

            say("\nDemo OK")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
