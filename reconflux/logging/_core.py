"""Logging setup for Reconflux."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

_FMT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: int | str = logging.INFO,
    *,
    colorized: bool = True,
    file_logging: bool = False,
) -> None:
    """Configure global logging for Reconflux.

    Clears all existing handlers and installs a single console handler on the
    root logger so every library log flows through the same configuration.

    Parameters
    ----------
    level:
        Minimum log level, e.g. ``logging.DEBUG`` or ``"DEBUG"``.
    colorized:
        Use Rich for coloured console output.  When ``False`` a plain
        :class:`logging.StreamHandler` is used instead.
    file_logging:
        Write logs to ``logs/reconflux_<YYYY-MM-DD>.log`` in addition to the
        console handler.
    """
    if isinstance(level, str):
        level = logging.getLevelName(level.strip().upper())

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    formatter = logging.Formatter(fmt=_FMT, datefmt=_DATEFMT)

    if colorized:
        from rich.logging import RichHandler

        console_handler: logging.Handler = RichHandler(
            rich_tracebacks=False,
            show_path=False,
            markup=False,
            omit_repeated_times=False,
        )
    else:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

    root.addHandler(console_handler)

    if file_logging:
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_path = Path("logs") / f"reconflux_{date_str}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
