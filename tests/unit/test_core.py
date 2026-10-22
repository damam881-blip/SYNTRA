import logging

import pytest

from app.core.config import get_settings
from app.core.logging import configure_logging


def test_settings_default_values(monkeypatch):
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    settings = get_settings()

    assert settings.app_name == "Network Simulator Backend"
    assert settings.app_version == "0.1.0"
    assert settings.log_level == "INFO"


def test_settings_environment_override(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Network Simulator Test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = get_settings()

    assert settings.app_name == "Network Simulator Test"
    assert settings.log_level == "DEBUG"


def test_logging_rejects_invalid_level():
    with pytest.raises(ValueError, match="Invalid logging level"):
        configure_logging("INVALID_LEVEL")


def test_logging_does_not_duplicate_handlers():
    configure_logging("INFO")
    configure_logging("DEBUG")

    logger = logging.getLogger("network_simulator")

    assert len(logger.handlers) == 1
    assert logger.level == logging.DEBUG


def test_logging_respects_level():
    configure_logging("WARNING")

    logger = logging.getLogger("network_simulator")

    assert logger.isEnabledFor(logging.WARNING)
    assert not logger.isEnabledFor(logging.INFO)
