from __future__ import annotations

import warnings as py_warnings


class ReconfluxWarning(UserWarning):
    """The base class for all of the warnings emitted by reconflux"""

    pass


def emit_internal_warning(
    message: str,
    *,
    category: type[ReconfluxWarning] = ReconfluxWarning,
    stacklevel: int = 2,
) -> None:
    """
    Emits a ``ReconfluxWarning`` subclass, this is to ensure
    all warnings emitted can by the library can easily be turned
    off by users
    """
    py_warnings.warn(
        message=message,
        category=category,
        stacklevel=stacklevel,
    )
