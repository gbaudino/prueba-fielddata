import asyncio

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from agroclimate.api.dependencies import SessionDep

logger = structlog.get_logger()

READINESS_TIMEOUT_SECONDS = 2

router = APIRouter()


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(session: SessionDep) -> dict[str, str]:
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        logger.warning(
            "database_readiness_check_failed",
            error=type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    return {"status": "ok"}
