from fastapi import APIRouter

from agroclimate.api.v1.alerts.router import router as alerts_router
from agroclimate.api.v1.notifications.router import (
    router as notifications_router,
)

router = APIRouter()
router.include_router(alerts_router)
router.include_router(notifications_router)
