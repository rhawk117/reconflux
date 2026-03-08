"""File system utilities for the Reconflux CLI.

Provides path resolution and file operations used across the CLI.
All errors raised are subclasses of ``ReconfluxError``.
"""

from __future__ import annotations

import dataclasses as dc
import importlib.util
import os
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, ParamSpec, TypeVar

import anyio

from reconflux.core import FileSystemError

if TYPE_CHECKING:
    from collections.abc import Callable

type PathLike = str | os.PathLike[str]

Parameters = ParamSpec('Parameters')
ReturnType = TypeVar('ReturnType')





class PackageResolutionError(FileSystemError):

    default_message: ClassVar[str] = 'Could not resolve the reconflux package directory.'
    error_code: ClassVar[str] = 'package_resolution_error'


def _coerce_path(path: PathLike) -> Path:
    """Convert a path-like value into a ``Path`` instance.

    Parameters
    ----------
    path : PathLike
        A string or path-like object.

    Returns
    -------
    Path
        The normalized ``Path`` object.
    """
    return Path(path)


def get_package_dir(package_name: str) -> Path:
    """Return the directory containing the installed ``reconflux`` package.

    Returns
    -------
    Path
        The package directory.

    Raises
    ------
    PackageResolutionError
        If the package spec or its origin cannot be located.
    """
    package_spec = importlib.util.find_spec('reconflux')
    if package_spec is None or package_spec.origin is None:
        raise PackageResolutionError()

    return Path(package_spec.origin).resolve().parent



@dc.dataclass(slots=True)
class ReconfluxFileSystem:
    package_name: str = 'reconflux'
    hidden_dir_prefix: str = '.'
    package_dir:



    @property
    def appdata_dirname(self) -> str:
        template = '{hidden}{app_name}_appdata'
        return template.format(
            hidden=self.hidden_dir_prefix,
            app_name=self.package_name,
        )

    def resolve_app_data_dir(self) -> Path:





def get_app_data_dir(
    app_name: str = 'reconflux',
    *,
    hidden_dir_prefix: str = '.',
) -> Path:
    """Return the application-local data directory.

    The data directory is created conceptually adjacent to the installed
    application package directory using the naming pattern
    ``.<app_name>_appdata``.

    Examples
    --------
    If the package directory resolves to:

    ``/some/path/site-packages/reconflux``

    then the app data directory becomes:

    ``/some/path/site-packages/.reconflux_appdata``

    Parameters
    ----------
    app_name : str, default='reconflux'
        The application name used to build the hidden directory name.
    hidden_dir_prefix : str, default='.'
        Prefix used for the generated application data directory.

    Returns
    -------
    Path
        The application-local data directory path.

    Raises
    ------
    PackageResolutionError
        If the package directory cannot be resolved.
    """
    package_dir = get_package_dir()
    directory_name = f'{hidden_dir_prefix}{app_name}_appdata'
    return package_dir.parent / directory_name


def get_user_config_dir(app_name: str = 'reconflux') -> Path:
    """Return the application-local configuration directory.

    Parameters
    ----------
    app_name : str, default='reconflux'
        The application name used to build the data directory.

    Returns
    -------
    Path
        The application-local configuration directory.
    """
    return get_app_data_dir(app_name) / 'config'


def get_user_data_dir(app_name: str = 'reconflux') -> Path:
    """Return the application-local data directory.

    Parameters
    ----------
    app_name : str, default='reconflux'
        The application name used to build the data directory.

    Returns
    -------
    Path
        The application-local data directory.
    """
    return get_app_data_dir(app_name) / 'data'


def ensure_dir(path: PathLike) -> Path:
    """Create a directory and its parents if needed.

    Parameters
    ----------
    path : PathLike
        The directory path to create.

    Returns
    -------
    Path
        The resolved directory path.

    Raises
    ------
    FileSystemError
        If the directory cannot be created.
    """
    directory_path = _coerce_path(path)

    try:
        directory_path.mkdir(parents=True, exist_ok=True)
        return directory_path.resolve()
    except OSError as exc:
        raise FileSystemError.from_os_error(
            operation='create directory',
            path=directory_path,
            exc=exc,
        ) from exc


def read_text(path: PathLike, *, encoding: str = 'utf-8') -> str:
    """Read a text file.

    Parameters
    ----------
    path : PathLike
        The file path to read.
    encoding : str, default='utf-8'
        The text encoding.

    Returns
    -------
    str
        The file contents.

    Raises
    ------
    FileSystemError
        If the file cannot be read.
    """
    file_path = _coerce_path(path)

    try:
        return file_path.read_text(encoding=encoding)
    except OSError as exc:
        raise FileSystemError.from_os_error(
            operation='read file',
            path=file_path,
            exc=exc,
        ) from exc


def write_text(
    path: PathLike,
    content: str,
    *,
    encoding: str = 'utf-8',
) -> Path:
    """Write text to a file, creating parent directories as needed.

    Parameters
    ----------
    path : PathLike
        The destination file path.
    content : str
        The text content to write.
    encoding : str, default='utf-8'
        The text encoding.

    Returns
    -------
    Path
        The resolved file path.

    Raises
    ------
    FileSystemError
        If the file cannot be written.
    """
    file_path = _coerce_path(path)

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding=encoding)
        return file_path.resolve()
    except OSError as exc:
        raise FileSystemError.from_os_error(
            operation='write file',
            path=file_path,
            exc=exc,
        ) from exc


def delete_file(path: PathLike, *, missing_ok: bool = True) -> None:
    """Delete a file.

    Parameters
    ----------
    path : PathLike
        The file path to delete.
    missing_ok : bool, default=True
        Whether a missing file should be ignored.

    Raises
    ------
    FileSystemError
        If the file exists but cannot be deleted.
    """
    file_path = _coerce_path(path)

    try:
        file_path.unlink(missing_ok=missing_ok)
    except OSError as exc:
        raise FileSystemError.from_os_error(
            operation='delete file',
            path=file_path,
            exc=exc,
        ) from exc


def path_exists(path: PathLike) -> bool:
    """Return whether a path exists.

    Parameters
    ----------
    path : PathLike
        The path to inspect.

    Returns
    -------
    bool
        ``True`` if the path exists, otherwise ``False``.
    """
    return _coerce_path(path).exists()


def resolve_path(path: PathLike, *, strict: bool = False) -> Path:
    """Resolve a path to an absolute path.

    Parameters
    ----------
    path : PathLike
        The path to resolve.
    strict : bool, default=False
        Whether resolution should fail if the path does not exist.

    Returns
    -------
    Path
        The resolved path.

    Raises
    ------
    FileSystemError
        If strict resolution fails.
    """
    raw_path = _coerce_path(path)

    try:
        return raw_path.resolve(strict=strict)
    except OSError as exc:
        raise FileSystemError.from_os_error(
            operation='resolve path',
            path=raw_path,
            exc=exc,
        ) from exc


async def run_sync_file_op[**Parameters, ReturnType](
    func: Callable[Parameters, ReturnType],
    /,
    *args: Parameters.args,
    **kwargs: Parameters.kwargs,
) -> ReturnType:
    """Run a blocking file system operation in a worker thread.

    Parameters
    ----------
    func : Callable[Parameters, ReturnType]
        The synchronous callable to execute.
    *args : Parameters.args
        Positional arguments passed to the callable.
    **kwargs : Parameters.kwargs
        Keyword arguments passed to the callable.

    Returns
    -------
    ReturnType
        The callable result.
    """
    return await anyio.to_thread.run_sync(lambda: func(*args, **kwargs))


async def ensure_dir_async(path: PathLike) -> Path:
    """Async wrapper around :func:`ensure_dir`.

    Parameters
    ----------
    path : PathLike
        The directory path to create.

    Returns
    -------
    Path
        The resolved directory path.
    """
    return await run_sync_file_op(ensure_dir, path)


async def read_text_async(
    path: PathLike,
    *,
    encoding: str = 'utf-8',
) -> str:
    """Async wrapper around :func:`read_text`.

    Parameters
    ----------
    path : PathLike
        The file path to read.
    encoding : str, default='utf-8'
        The text encoding.

    Returns
    -------
    str
        The file contents.
    """
    return await run_sync_file_op(read_text, path, encoding=encoding)


async def write_text_async(
    path: PathLike,
    content: str,
    *,
    encoding: str = 'utf-8',
) -> Path:
    """Async wrapper around :func:`write_text`.

    Parameters
    ----------
    path : PathLike
        The destination file path.
    content : str
        The text content to write.
    encoding : str, default='utf-8'
        The text encoding.

    Returns
    -------
    Path
        The resolved file path.
    """
    return await run_sync_file_op(
        write_text,
        path,
        content,
        encoding=encoding,
    )


async def delete_file_async(
    path: PathLike,
    *,
    missing_ok: bool = True,
) -> None:
    """Async wrapper around :func:`delete_file`.

    Parameters
    ----------
    path : PathLike
        The file path to delete.
    missing_ok : bool, default=True
        Whether a missing file should be ignored.
    """
    await run_sync_file_op(delete_file, path, missing_ok=missing_ok)


async def path_exists_async(path: PathLike) -> bool:
    """Async wrapper around :func:`path_exists`.

    Parameters
    ----------
    path : PathLike
        The path to inspect.

    Returns
    -------
    bool
        ``True`` if the path exists, otherwise ``False``.
    """
    return await run_sync_file_op(path_exists, path)


async def resolve_path_async(
    path: PathLike,
    *,
    strict: bool = False,
) -> Path:
    """Async wrapper around :func:`resolve_path`.

    Parameters
    ----------
    path : PathLike
        The path to resolve.
    strict : bool, default=False
        Whether resolution should fail if the path does not exist.

    Returns
    -------
    Path
        The resolved path.
    """
    return await run_sync_file_op(resolve_path, path, strict=strict)
