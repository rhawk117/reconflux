"""Async-safe logging setup for the Reconflux library."""

from __future__ import annotations

import atexit
import contextlib
import logging
import logging.handlers
import queue
import sys
from typing import IO, NamedTuple

from rich.console import Console
from rich.logging import RichHandler

from reconflux.logging._config import FileConfig, LoggingConfig, RichConfig, StreamConfig


class ExactLevelFilter(logging.Filter):
    def __init__(self, level: int) -> None:
        super().__init__()
        self._level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == self._level


class ExcludeLevelFilter(logging.Filter):
    def __init__(self, *levels: int) -> None:
        super().__init__()
        self._levels = frozenset(levels)

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno not in self._levels


class LoggerHandle(NamedTuple):
    """Opaque handle returned by :func:`initialize_logging`."""
    queue_listener: logging.handlers.QueueListener
    queue_handler: logging.handlers.QueueHandler
    logger: logging.Logger

    def shutdown(self) -> None:
        """Stop the queue listener and detach the handler."""
        try:
            self.queue_listener.stop()
        finally:
            self.logger.removeHandler(self.queue_handler)




def new_formatter(config: LoggingConfig) -> logging.Formatter:
    return logging.Formatter(fmt=config.format.fmt, datefmt=config.format.datefmt)


def create_rich_handlers(
    rich: RichConfig,
    formatter: logging.Formatter,
    base_level: int,
) -> list[logging.Handler]:
    level = rich.level if rich.level is not None else base_level

    def new_rich_handler(*, stderr: bool, filters: list[logging.Filter]) -> logging.Handler:
        console = Console(stderr=stderr)
        handler = RichHandler(
            level=level,
            console=console,
            rich_tracebacks=rich.rich_tracebacks,
            markup=rich.markup,
            show_path=rich.show_path,
            omit_repeated_times=rich.omit_repeated_times,
        )
        handler.setFormatter(formatter)
        for f in filters:
            handler.addFilter(f)
        return handler

    if rich.install_rich_tracebacks:
        with contextlib.suppress(ImportError):
            from rich.traceback import install as install_tracebacks

            install_tracebacks(show_locals=rich.show_traceback_locals)

    return [
        new_rich_handler(
            stderr=False,
            filters=[ExactLevelFilter(logging.WARNING)],
        ),
        new_rich_handler(
            stderr=True,
            filters=[ExcludeLevelFilter(logging.WARNING)],
        ),
    ]


def create_stream_handler(
    stream: StreamConfig,
    formatter: logging.Formatter,
    base_level: int,
) -> list[logging.Handler]:
    level = stream.level if stream.level is not None else base_level

    def new_handler(
        *,
        target: IO,
        handler_level: int,
        filters: list[logging.Filter],
    ) -> logging.StreamHandler:
        handler = logging.StreamHandler(target)
        handler.setLevel(handler_level)
        handler.setFormatter(formatter)
        for f in filters:
            handler.addFilter(f)
        return handler

    return [
        new_handler(
            target=sys.stdout,
            handler_level=logging.WARNING,
            filters=[ExactLevelFilter(logging.WARNING)],
        ),
        new_handler(
            target=sys.stderr,
            handler_level=level,
            filters=[ExcludeLevelFilter(logging.WARNING)],
        ),
    ]


def create_file_handler(
    file: FileConfig,
    formatter: logging.Formatter,
    base_level: int,
) -> logging.Handler:
    level = file.level if file.level is not None else base_level
    file.path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        filename=file.path,
        maxBytes=file.max_megabytes * 1024 * 1024,
        backupCount=file.backup_count,
        encoding=file.encoding,
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler




def initialize_logging(config: LoggingConfig | None = None) -> LoggerHandle:
    """Set up async-safe logging from a :class:`LoggingConfig`.

    Parameters
    ----------
    config : LoggingConfig | None
        Logging configuration.  Defaults to ``LoggingConfig()`` which
        enables Rich console output at INFO level.

    Returns
    -------
    LoggerHandle
        A handle that can be used to shut down the logging system.
        Shutdown is also registered with :mod:`atexit`.

    Examples
    --------
    Minimal::

        handle = initialize_logging()

    From a TOML file::

        from pydantic import TypeAdapter
        import tomllib

        with open("pyproject.toml", "rb") as f:
            raw = tomllib.load(f)

        config = TypeAdapter(LoggingConfig).validate_python(raw["logging"])
        handle = initialize_logging(config)
    """
    config = config or LoggingConfig()
    formatter = new_formatter(config)
    handlers: list[logging.Handler] = []

    if config.rich.enabled:
        handlers.extend(create_rich_handlers(config.rich, formatter, config.level))

    if config.stream.enabled:
        handlers.extend(create_stream_handler(config.stream, formatter, config.level))

    if config.file.enabled:
        handlers.append(create_file_handler(config.file, formatter, config.level))

    if not handlers:
        handlers.append(logging.NullHandler())

    log_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_listener = logging.handlers.QueueListener(
        log_queue,
        *handlers,
        respect_handler_level=True,
    )

    logger = logging.getLogger(config.logger_name)
    logger.handlers.clear()
    logger.setLevel(config.level)
    logger.propagate = config.propagate
    logger.addHandler(queue_handler)

    queue_listener.start()

    handle = LoggerHandle(
        queue_listener=queue_listener,
        queue_handler=queue_handler,
        logger=logger,
    )
    atexit.register(handle.shutdown)
    return handle