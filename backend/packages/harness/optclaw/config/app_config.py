import logging
import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Self

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from optclaw.config.model_config import ModelConfig
from optclaw.config.paths import Paths

load_dotenv()

logger = logging.getLogger(__name__)


class AppConfig(BaseModel):
    """Config for the optclaw application"""

    log_level: str = Field(default="info", description="Logging level for optclaw modules (debug/info/warning/error)")
    models: list[ModelConfig] = Field(default_factory=list, description="Available models")


    @classmethod
    def from_file(cls, config_path: str | None = None) -> Self:
        """Load config from YAML file.

        Args:
            config_path: Path to the config file.

        Returns:
            AppConfig: The loaded config.
        """
        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        return cls.model_validate(config_data)

    def get_model_config(self, name: str) -> ModelConfig | None:
        """Get the model config by name.

        Args:
            name: The name of the model to get the config for.

        Returns:
            The model config if found, otherwise None.
        """
        return next((model for model in self.models if model.name == name), None)


_app_config: AppConfig | None = None


def _get_config_mtime(config_path: Path) -> float | None:
    """Get the modification time of a config file if it exists."""
    try:
        return config_path.stat().st_mtime
    except OSError:
        return None


def get_app_config() -> AppConfig:
    """Get the config instance.
    """
    global _app_config

    # read project yaml
    config_path = Path(f'{Paths().base_dir.parent}/config.yaml')
    current_mtime = _get_config_mtime(config_path)

    _app_config = AppConfig.from_file(str(config_path))

    logger.info(f"Loading config from {config_path} (mtime={current_mtime})")

    return _app_config