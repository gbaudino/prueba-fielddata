import json
import logging

import pytest
import structlog
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from agroclimate.core.config import Settings
from agroclimate.core.observability import configure_observability


@pytest.fixture
def production_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"environment": "production"})


def test_structlog_events_are_json(
    production_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_observability(production_settings)

    structlog.get_logger().info("alert_sent", alert_id=1)

    log = json.loads(capsys.readouterr().out)
    assert log["event"] == "alert_sent"
    assert log["alert_id"] == 1
    assert log["level"] == "info"
    assert "timestamp" in log


def test_exceptions_are_structured(
    production_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_observability(production_settings)

    try:
        int("not a number")
    except ValueError:
        structlog.get_logger().exception("conversion_failed")

    log = json.loads(capsys.readouterr().out)
    assert log["event"] == "conversion_failed"
    assert log["exception"][0]["exc_type"] == "ValueError"


def test_standard_library_logs_use_the_same_format(
    production_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_observability(production_settings)

    logging.getLogger("some.library").warning("something happened")

    log = json.loads(capsys.readouterr().out)
    assert log["event"] == "something happened"
    assert log["logger"] == "some.library"
    assert log["level"] == "warning"


def test_fastapi_requests_are_logged_and_correlated(
    client: TestClient,
) -> None:
    request_id = "fielddata-test-request"

    with capture_logs() as logs:
        response = client.get(
            "/health/live",
            headers={"X-Request-ID": request_id},
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id

    request_logs = [
        log for log in logs if log["event"] == "http_request_completed"
    ]
    assert len(request_logs) == 1
    assert request_logs[0]["request_id"] == request_id
    assert request_logs[0]["method"] == "GET"
    assert request_logs[0]["path"] == "/health/live"
    assert request_logs[0]["status_code"] == 200
    assert request_logs[0]["duration_ms"] >= 0
