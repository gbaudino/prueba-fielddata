# agroclimate - Prueba FieldData

Sistema de alertas climaticas para el agro. Consume usuarios, campos y
pronosticos existentes en Agrobot y administra alertas y notificaciones.

## Stack

- Python 3.14
- FastAPI
- PostgreSQL
- SQLAlchemy async
- Alembic
- Pydantic
- Docker
- uv

## Requisitos

- [Docker](https://docs.docker.com/engine/install/)
- [uv](https://github.com/astral-sh/uv#installation)

## Primeros pasos

```bash
cp .env.example .env
uv sync --locked
make start
make migrate-up
```

Swagger: `http://localhost:8000/docs`.

`make start` levanta PostgreSQL, carga datos locales de demostración y levanta
la API. El dataset se genera desde `scripts/seed_db.py`. Eso no se incluye en la imagen de producción.


## API

Las rutas requieren `X-User-Id`, usado como identidad simulada para el
challenge. En producción debe ser validado por la capa de autenticación de
Agrobot.

- `POST /v1/alerts`
- `GET /v1/alerts` (filtros y cursor)
- `GET/PATCH/DELETE /v1/alerts/{id}`
- `GET /v1/notifications` (filtros y cursor)
- `POST /v1/notifications/read`

## Modelo

Agrobot administra `users`, `fields` y `weather_forecasts`. Agroclimate solo
los consulta y administra `alerts` y `notifications`. Las alertas son
personales por usuario, campo y tipo de evento.
