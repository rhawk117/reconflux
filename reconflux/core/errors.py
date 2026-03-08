from typing import TYPE_CHECKING, Any, ClassVar
import anyio
if TYPE_CHECKING:
    from pathlib import Path


class ReconfluxError(Exception):
    """
    The base class for all Reconflux Exceptions

    Class Variables
    ----------------
    default_message : str
        The default message for when the caller does not provide one
        default 'An unhandled runtime error from Reconflux occured'
    error_code : str
        A code assigned for the error, default 'reconflux_error'
    """

    default_message: ClassVar[str] = 'An unhandled runtime error from Reconflux occured'
    error_code: ClassVar[str] = 'reconflux_error'

    def __init__(
        self, message: str | None = None, *, context: dict[str, Any] | None = None
    ) -> None:
        self.message = message or self.default_message
        self.context = context or {}
        super().__init__(self.message)

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def __str__(self) -> str:
        if not self.context:
            return self.message

        context_items = ', '.join(
            f'{key}={value!r}' for key, value in self.context.items()
        )
        return f'{self.name}: {self.message} [{context_items}]'


class ReconfluxValidationError(ReconfluxError):
    error_code = 'validation_error'
    default_message = 'One or more validation error(s) occured.'

class FileSystemError(ReconfluxError):
    """Raised when a file system operation fails."""

    default_message: ClassVar[str] = 'A file system error occurred.'
    error_code: ClassVar[str] = 'fs_error'

    @classmethod
    def from_os_error(
        cls,
        *,
        operation: str,
        path: Path | anyio.Path,
        exc: OSError,
    ) -> FileSystemError:
        """Create a normalized file system error from an ``OSError``.

        Parameters
        ----------
        operation : str
            The file system operation that failed.
        path : Path
            The path involved in the failed operation.
        exc : OSError
            The original operating system exception.

        Returns
        -------
        FileSystemError
            A normalized application-specific file system error.
        """
        return cls(
            f"Could not {operation} '{path}'",
            context={
                'path': str(path),
                'operation': operation,
                'reason': str(exc),
            },
        )
