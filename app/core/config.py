import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "Network Simulator Backend"
    app_version: str = "0.1.0"
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv(
            "APP_NAME",
            "Network Simulator Backend",
        ),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
