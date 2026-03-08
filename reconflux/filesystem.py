import contextlib
from typing import TYPE_CHECKING

import anyio

from reconflux.core import FileSystemError

if TYPE_CHECKING:
    import os
    from collections.abc import Generator



async def filepath(
    path: os.PathLike,
    *,
    resolve: bool = False,
) -> anyio.Path:
    path = anyio.Path(path)
    if resolve:
        path = await path.resolve()
    return path


@contextlib.contextmanager
def wrap_os_error(operation: str, path: anyio.Path) -> Generator[None]:
    try:
        yield
    except OSError as exc:
        raise FileSystemError.from_os_error(
            operation=operation, path=path, exc=exc
        ) from exc


async def get_cwd(
    *join: str,
    resolve: bool = False,
) -> anyio.Path:
    cwd = await anyio.Path.cwd()
    if resolve:
        cwd = await cwd.resolve()
    if join:
        cwd = cwd.joinpath(*join)
    return cwd


async def read_text_async(path: os.PathLike, *, encoding: str = 'utf-8') -> str:
    path = anyio.Path(path)
    with wrap_os_error('read text', path):
        return await path.read_text(encoding=encoding)


async def write_text_async(
    path: os.PathLike, *, text: str, encoding: str = 'utf-8'
) -> None:
    path = anyio.Path(path)
    with wrap_os_error('write text', path):
        await path.write_text(
            text,
            encoding=encoding,
        )


async def read_bytes_async(path: os.PathLike) -> bytes:
    path = anyio.Path(path)
    with wrap_os_error('read bytes', path):
        return await path.read_bytes()
