import asyncio
import subprocess
from typing import Any

import httpx2
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncEngine

from agroclimate.db.session import create_engine
from agroclimate.db.settings import get_database_settings

API_URL = "http://localhost:8000"
THRESHOLD = 60

FIND_TARGET = text(
    """
    select
        f.id as field_id,
        u.id as user_id,
        wf.event_type,
        count(*) as matches
    from fields f
    join users u on u.id = f.related_users[1]
    join weather_forecasts wf on wf.field_id = f.id
    where wf.probability >= :threshold
      and not exists (
          select 1
          from alerts a
          where a.user_id = u.id
            and a.field_id = f.id
            and a.event_type = wf.event_type
      )
    group by f.id, u.id, wf.event_type
    order by matches desc, f.id
    limit 1
    """
)


async def find_target(engine: AsyncEngine) -> Row[Any] | None:
    async with engine.connect() as connection:
        result = await connection.execute(
            FIND_TARGET,
            {"threshold": THRESHOLD},
        )
        return result.first()


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
    engine = create_engine(get_database_settings().database_url)
    try:
        target = await find_target(engine)
        if target is None:
            print(
                "No hay un campo libre para el demo. "
                "Proba reseteando el volumen.",
                flush=True,
            )
            return 1

        headers = {"X-User-Id": str(target.user_id)}
        async with httpx2.AsyncClient(
            base_url=API_URL,
            timeout=15,
        ) as client:
            if not await wait_for_api(client):
                print(
                    "La API no esta corriendo. Ejecuta `make start` primero.",
                    flush=True,
                )
                return 1

            created = await client.post(
                "/v1/alerts",
                headers=headers,
                json={
                    "field_id": str(target.field_id),
                    "event_type": target.event_type,
                    "threshold": THRESHOLD,
                },
            )
            if created.status_code != 201:
                print(
                    f"No se pudo crear la alerta: {created.text}", flush=True
                )
                return 1

            alert_id = created.json()["id"]
            print(f"Usuario demo: {target.user_id}", flush=True)
            print(f"Campo demo:   {target.field_id}", flush=True)
            print(f"Evento:       {target.event_type}", flush=True)
            print(f"Umbral:       {THRESHOLD}", flush=True)
            print(f"Pronosticos:  {target.matches}", flush=True)
            print(f"Alerta:       {alert_id}", flush=True)

            before = await list_notifications(
                client,
                headers,
                str(target.field_id),
                alert_id,
            )
            print(
                f"Notificaciones antes del worker: {len(before)}", flush=True
            )

            run_worker()
            first = await list_notifications(
                client,
                headers,
                str(target.field_id),
                alert_id,
            )
            print(
                f"Notificaciones despues del primer worker: {len(first)}",
                flush=True,
            )

            run_worker()
            second = await list_notifications(
                client,
                headers,
                str(target.field_id),
                alert_id,
            )
            print(
                f"Notificaciones despues del segundo worker: {len(second)}",
                flush=True,
            )

            if not first:
                print("El worker no genero notificaciones.", flush=True)
                return 1
            if len(first) != len(second):
                print("El segundo worker duplico notificaciones.", flush=True)
                return 1

            print("OK: la evaluacion es idempotente.", flush=True)
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
