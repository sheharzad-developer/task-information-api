"""Application settings, read from environment variables.

Everything is configurable through env vars so the same image can run
locally, in CI and on AWS ECS without being rebuilt.
"""

import os
from dataclasses import dataclass, field

from app import __version__


@dataclass(frozen=True)
class Settings:
    app_name: str = field(default_factory=lambda: os.getenv("APP_NAME", "task-api"))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "local"))
    # The CI/CD pipeline injects the git commit SHA so /health shows exactly
    # which build is running.
    version: str = field(default_factory=lambda: os.getenv("APP_VERSION", __version__))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())


def get_settings() -> Settings:
    return Settings()
