"""TOML-backed logging configuration via pydantic-settings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, BeforeValidator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

_LEVEL_NAMES = logging.getLevelNamesMapping()

_DEFAULT_LOGGING_TOML_FILE = Path('settings', 'logging.toml')


def _parse_log_level(value: int | str) -> int:
    if isinstance(value, int):
        return value
    name = value.strip().upper()
    if name not in _LEVEL_NAMES:
        raise ValueError(f"Unknown log level: {value!r}")
    return _LEVEL_NAMES[name]


LogLevel = Annotated[int, BeforeValidator(_parse_log_level)]


class FormatConfig(BaseModel):
    fmt: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt: str = "%Y-%m-%d %H:%M:%S"


class RichConfig(BaseModel):
    enabled: bool = True
    rich_tracebacks: bool = False
    install_rich_tracebacks: bool = False
    show_traceback_locals: bool = False
    markup: bool = False
    show_path: bool = False
    omit_repeated_times: bool = False
    level: LogLevel | None = None


class FileConfig(BaseModel):
    enabled: bool = False
    path: Path = Path("logs/reconflux.log")
    level: LogLevel | None = None
    max_megabytes: int = 5
    backup_count: int = 5
    encoding: str = "utf-8"


class StreamConfig(BaseModel):
    """Plain stream handler settings (no Rich)."""

    enabled: bool = False
    level: LogLevel | None = None


class LoggingConfig(BaseSettings):
    """Logging configuration loaded from a TOML file.

    By default, reads from ``reconflux.logging.toml`` in the working directory.
    The file path can be overridden via ``model_config`` or by subclassing.

    Source priority (highest to lowest):
        1. Init kwargs (direct Python construction)
        2. Environment variables (prefixed ``RECONFLUX_``)
        3. TOML file

    Examples
    --------
    TOML file (``reconflux.toml``)::

        logger_name = "myapp"
        level = "DEBUG"

        [rich]
        enabled = true
        rich_tracebacks = true

        [file]
        enabled = true
        path = "logs/myapp.log"

    Python::

        # Defaults (no TOML file required)
        config = LoggingConfig()

        # Direct construction (takes priority over TOML/env)
        config = LoggingConfig(level="DEBUG", rich=RichConfig(rich_tracebacks=True))
    """

    model_config = SettingsConfigDict(
        toml_file=_DEFAULT_LOGGING_TOML_FILE,
        extra="ignore",
    )

    logger_name: str = "reconflux"
    level: LogLevel = logging.INFO
    propagate: bool = False
    format: FormatConfig = FormatConfig()
    rich: RichConfig = RichConfig()
    file: FileConfig = FileConfig()
    stream: StreamConfig = StreamConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            TomlConfigSettingsSource(settings_cls),
        )