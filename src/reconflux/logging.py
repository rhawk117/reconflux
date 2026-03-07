from __future__ import annotations

import abc
import atexit
from collections.abc import Sequence
import contextlib
import logging
import logging.handlers
import queue
import sys
import dataclasses as dc
from pathlib import Path
from typing import IO, NamedTuple, Self
from xml.sax import handler
from rich.console import Console
from rich.logging import RichHandler

_LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


class ExactLevelFilter(logging.Filter):
    def __init__(self, level: int) -> None:
        super().__init__()
        self._level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == self._level


class ExcludeLevelFilter(logging.Filter):
    def __init__(self, *levels: int) -> None:
        super().__init__()
        self._levels = set(levels)

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno not in self._levels

def get_default_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
    )



@dc.dataclass(slots=True)
class RichLogging:
    formatter: logging.Formatter
    rich_tracebacks: bool = False
    markup: bool = False
    show_path: bool = False
    omit_repeated_times: bool = False
    show_traceback_locals: bool = False

    def handler(
        self,
        *,
        use_stderr: bool,
        level: int,
        filters: list[logging.Filter] | None = None,
    ) -> logging.Handler:
        console = Console(stderr=use_stderr)
        handler = RichHandler(
            level=level,
            console=console,
            rich_tracebacks=self.rich_tracebacks,
            markup=self.markup,
            show_path=self.show_path,
            omit_repeated_times=self.omit_repeated_times,
        )
        handler.setFormatter(self.formatter)
        for active_filter in filters or []:
            handler.addFilter(active_filter)

        return handler

    def install_rich_tracebacks(self) -> None:
        with contextlib.suppress(ImportError):
            from rich.traceback import install as install_tracebacks
            install_tracebacks(show_locals=self.show_traceback_locals)


def new_streamhandler(
    *,
    stream: IO,
    level: int,
    formatter: logging.Formatter,
    filters: list[logging.Filter] | None = None,
) -> logging.StreamHandler:
    handler = logging.StreamHandler(stream)
    handler.setLevel(level)
    handler.setFormatter(formatter)

    for active_filter in filters or []:
        handler.addFilter(active_filter)

    return handler



class _AsyncSafeLogger(NamedTuple):
    queue_listener: logging.handlers.QueueListener
    queue_handler: logging.handlers.QueueHandler
    logger: logging.Logger

    def shutdown(self) -> None:
        try:
            self.queue_listener.stop()
        finally:
            self.logger.removeHandler(self.queue_handler)




class ReconfluxLoggerInstaller:
    def __init__(
        self,
        *,
        propagate: bool = False,
        log_level: int = logging.INFO,
        formatter: logging.Formatter | None = None,
    ) -> None:
        self.handlers: list[logging.Handler] = []
        self.propagate: bool = propagate
        self.log_level: int = log_level
        self.formatter = formatter or get_default_formatter()

    def pretty_handler(
        self,
        *,
        rich_tracebacks: bool = False,
        level: int | None = None,
        markup: bool = False,
        show_path: bool = False,
        omit_repeated_times: bool = False,
        show_traceback_locals: bool = False,
        formatter: logging.Formatter | None = None
    ) -> Self:
        if level is None:
            level = self.log_level

        plugin = RichLogging(
            markup=markup,
            show_path=show_path,
            omit_repeated_times=omit_repeated_times,
            show_traceback_locals=show_traceback_locals,
            formatter=formatter or self.formatter
        )
        stdout_handler = plugin.handler(
            use_stderr=False,
            level=logging.WARNING,
            filters=[ExactLevelFilter(logging.WARNING)],
        )
        stderr_handler = plugin.handler(
            use_stderr=True,
            level=self.log_level,
            filters=[ExcludeLevelFilter(logging.WARNING)],
        )
        if rich_tracebacks:
            plugin.install_rich_tracebacks()

        self.handlers.extend([stdout_handler, stderr_handler])
        return self

    def stream_handler(
        self,
        *,
        level: int | None = None,
        formatter: logging.Formatter | None = None,
    ) -> None:
        if level is None:
            level = self.log_level

        formatter = formatter or self.formatter
        stderr_handler = new_streamhandler(
            stream=sys.stderr,
            level=level,
            filters=[ExcludeLevelFilter(logging.WARNING)],
            formatter=formatter
        )
        stdout_warning_handler = new_streamhandler(
            stream=sys.stdout,
            level=logging.WARNING,
            filters=[ExactLevelFilter(logging.WARNING)],
            formatter=formatter
        )
        self.handlers.extend([stderr_handler, stdout_warning_handler])

    def file_handler(
        self,
        *,
        file_path: str = 'logs/reconflux.log',
        level: int | None = None,
        max_megabytes: int = 5,
        backup_count: int = 5,
        encoding: str = 'utf-8',
        formatter: logging.Formatter | None = None
    ) -> None:
        if level is None:
            level = self.log_level

        max_bytes = max_megabytes * 1024 * 1024
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rotating_file_handler = logging.handlers.RotatingFileHandler(
            filename=path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding=encoding,
        )
        rotating_file_handler.setLevel(self.log_level)
        rotating_file_handler.setFormatter(formatter or self.formatter)
        self.handlers.append(rotating_file_handler)

    def install(
        self,
        *,
        propagate: bool = False,
        respect_handler_level: bool = True,
        logger_name: str = 'reconflux',
    ) -> None:
        logqueue = queue.SimpleQueue()
        queue_handler = logging.handlers.QueueHandler(logqueue)
        queue_listener = logging.handlers.QueueListener(
            logqueue,
            *self.handlers,
            respect_handler_level=respect_handler_level
        )
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.setLevel(self.log_level)
        logger.propagate = propagate
        logger.addHandler(queue_handler)

        queue_listener.start()

        async_logger = _AsyncSafeLogger(
            queue_listener=queue_listener,
            queue_handler=queue_handler,
            logger=logger,
        )
        atexit.register(async_logger.shutdown)







@dc.dataclass(slots=True)
class AsyncSafeLogging:
    handlers: list[logging.Handler] = dc.field(default_factory=list)
    log_queue: queue.SimpleQueue = dc.field(default_factory=queue.SimpleQueue)
    queue_handler: logging.handlers.QueueHandler = dc.field(init=False)
    queue_listener: logging.handlers.QueueListener = dc.field(init=False)
    respect_handler_level: bool = True

    def __post_init__(self) -> None:
        self.queue_handler = logging.handlers.QueueHandler(self.log_queue)
        self.queue_listener = logging.handlers.QueueListener(
            self.log_queue,
            *self.handlers,
            respect_handler_level=True,
        )





def initialize_logging(
    *,
    logger_name: str = 'reconflux',
    propagate: bool = False,
    log_level: int = logging.INFO,
    reconflux_handlers: Sequence[ReconfluxLogHandler],
) -> None:
    handlers: list[logging.Handler] = []
    for reconflux_handler in reconflux_handlers:
        reconflux_handler.register_handler(handlers)

    log_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_listener = logging.handlers.QueueListener(
        log_queue,
        *handlers,
        respect_handler_level=True,
    )

    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.setLevel(log_level)
    logger.propagate = propagate
    logger.addHandler(queue_handler)

    queue_listener.start()






