# agroclimate - Prueba FieldData

Sistema de alertas climaticas para el agro, proyecto de prueba para FieldData.


## Stack

- Python 3.14
- FastAPI
- PostgreSQL
- SQLAlchemy (async)
- Alembic
- Pydantic
- Docker
- uv

## Requisitos

- [Docker](https://docs.docker.com/engine/install/)
- [uv](https://github.com/astral-sh/uv#installation)

## Primeros pasos

Clonar el repositorio y crear el archivo de configuración local:

```bash
git clone https://github.com/gbaudino/prueba-fielddata.git
cd prueba-fielddata
cp .env.example .env
```

Construir y levantar los servicios:

```bash
make start
```

El Swagger de la API estara en `http://localhost:8000/docs`.

## Tests

```bash
make test
```

Hoy cubre los health checks (liveness, readiness con la base disponible, caida y colgada) y la configuracion de logs.
