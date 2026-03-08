from __future__ import annotations

import dataclasses as dc
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from pydantic import ValidationError

from reconflux.app.appdata import AppDataFile
from reconflux.core import FileSystemError, ReconfluxModel, emit_internal_warning

_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def log_levelname_to_level(levelname: str) -> int:
    return logging.getLevelNamesMapping()[levelname.strip().upper()]


class LoggerJsonConfig(ReconfluxModel):
    message_format: str = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
    level: str | int = 'INFO'
    colorized: bool = True
    file_logging: bool = False




async def get_log_config_file(filename: str = 'logger.json') -> AppDataFile:
    return await AppDataFile.resolve(
        filename,
        must_exist=False
    )

@dc.dataclass(slots=True)
class LoggingExtension:
    file: AppDataFile
    config: LoggerJsonConfig

    @classmethod
    async def load(cls) -> Self:
        """
        Resolves the LoggerJsonConfig from the file system (if exists)

        Returns
        -------
        Self
        """
        config_file = await get_log_config_file()
        if not await config_file.exists():
            # no need to write to the file system if user hasn't changed
            # the logging behavior
            return cls(config_file, LoggerJsonConfig())

        try:
            contents = await config_file.read()
            config = LoggerJsonConfig.model_validate_json(contents)
        except ValidationError:
            emit_internal_warning(
                'The Logger config json file is invalid '
                'and as such the default settings will be used '
            )
            config = LoggerJsonConfig()

        return cls(config_file, config)

    async def update_config(self, **changes: Any) -> str | None:
        """
        Updates the config file, if no errors occur that changes
        are written to the file system. If an error occurs the
        error message is returned to the caller.

        Returns
        -------
        str | None
            None means no errors occured
        """
        try:
            self.config = self.config.model_copy(update=changes)
        except ValidationError as exc:
            return f'[{exc.title}] Invalid config changes: {exc!r}'

        try:
            await self.file.write(self.config.model_dump_json())
        except FileSystemError as exc:
            return exc.message

        return None

    def configure_loggers(self) -> None:
        """Configure global logging for Reconflux.

        Clears all existing handlers and installs a single console handler on the
        root logger so every library log flows through the same configuration.

        Parameters
        ----------
        config: LoggerJsonConfig | None
            The config for the logger.
        """
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(self.config.level)

        formatter = logging.Formatter(fmt=_FMT, datefmt=_DATEFMT)

        if self.config.colorized:
            from rich.logging import RichHandler

            console_handler: logging.Handler = RichHandler(
                rich_tracebacks=True,
                show_path=False,
                markup=False,
                omit_repeated_times=False,
            )
        else:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)

        root.addHandler(console_handler)

        if self.config.file_logging:
            date_str = datetime.now(UTC).strftime('%Y-%m-%d')
            log_path = Path('logs') / f'reconflux_{date_str}.log'
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding='utf-8')
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
