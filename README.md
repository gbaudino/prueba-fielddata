# Agroclimate - FieldData Challenge

API de alertas climáticas. Consume usuarios, campos y pronósticos existentes en
Agrobot; administra alertas y notificaciones.

## Stack

Python 3.14 · FastAPI · PostgreSQL · SQLAlchemy async · Alembic · Docker · uv.

## Ejecutar localmente

Requisitos: Docker y [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
uv sync --locked
make start
```

`make start` construye la imagen, inicia PostgreSQL, prepara las tablas externas
y datos demo, aplica las migraciones y levanta la API y el worker. Swagger:
`http://localhost:8000/docs`.

`make test` ejecuta los tests contra una base PostgreSQL independiente.
`make check` ejecuta Ruff y Mypy. `make coverage` genera el reporte de cobertura.

## Comportamiento

- Las alertas son personales por usuario, campo y evento. Cada una tiene un
  umbral de probabilidad.
- El evaluador considera todos los pronósticos disponibles desde la fecha
  actual local de cada campo, sin limitar la cantidad de días futuros.
- Se crea como máximo una notificación por alerta y fecha de pronóstico. Si la
  condición sigue activa, las evaluaciones posteriores no duplican la
  notificación. Una fecha futura distinta puede generar otra notificación.
- La notificación conserva snapshots de probabilidad y umbral.
- La identidad se simula con `X-User-Id`; en producción debe integrarse con la
  autenticación de Agrobot.

## API

- `POST/GET /v1/alerts`
- `GET/PATCH/DELETE /v1/alerts/{id}`
- `GET /v1/notifications`
- `POST /v1/notifications/read`

Las rutas requieren `X-User-Id`. Los recursos de Agrobot (`users`, `fields` y
`weather_forecasts`) son externos y de solo lectura para este servicio. El seed
local crea representaciones de esas tablas para desarrollo y tests.

## Worker

El worker evalúa periódicamente con el intervalo de `EVALUATION_INTERVAL_SECONDS`
y puede ejecutarse una sola vez con:

```bash
make worker-once
```

TODO: si Agrobot incorpora Airflow u otro orquestador, ejecutar `--once` después
de que la ingesta meteorológica termine y confirme sus cambios en PostgreSQL.

## Decisiones y límites

- PostgreSQL garantiza la idempotencia con `UNIQUE (alert_id, forecast_date)`
  y `ON CONFLICT DO NOTHING`; no se necesita un lock en memoria ni advisory
  lock para coordinar evaluaciones.
- No se implementa una política de re-notificación para la misma alerta y fecha.
  Si se necesita, se puede diseñar como mejora futura.
- No se integra WhatsApp ni un broker de mensajes. La API expone las
  notificaciones persistidas; la entrega a canales externos queda fuera del
  alcance del challenge.
- En producción, las tablas externas deben existir antes de aplicar Alembic.
  `make migrate-up` prepara automáticamente las tablas mock locales antes de
  ejecutar las migraciones.
