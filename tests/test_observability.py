from uuid import UUID

import pytest
import structlog

from agroclimate.core.config import AppSettings
from agroclimate.core.observability import (
    _build_renderer,
    sanitize_request_id,
)


def test_safe_request_id_is_preserved() -> None:
    assert sanitize_request_id("req-123.abc_DEF") == "req-123.abc_DEF"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "invalid value",
        "line\nbreak",
        "x" * 129,
    ],
)
def test_invalid_request_id_is_replaced(value: str | None) -> None:
    request_id = sanitize_request_id(value)

    assert request_id != value
    assert str(UUID(request_id)) == request_id


def test_production_uses_json_logs() -> None:
    settings = AppSettings(
        app_name="agroclimate-test",
        environment="production",
        log_level="INFO",
    )

    renderer = _build_renderer(settings)

    assert isinstance(renderer, structlog.processors.JSONRenderer)


def test_local_uses_human_readable_logs() -> None:
    settings = AppSettings(
        app_name="agroclimate-test",
        environment="local",
        log_level="INFO",
    )

    renderer = _build_renderer(settings)

    assert isinstance(renderer, structlog.dev.ConsoleRenderer)
