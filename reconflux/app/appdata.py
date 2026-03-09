
import os
from typing import Self

import anyio

from reconflux import filesystem
from reconflux.concurrency import run_concurrently
from reconflux.core import FileSystemError


class AppdataResolutionError(FileSystemError):
    default_message = 'Could not resolve the reconflux package directory.'
    error_code = 'package_resolution_error'


PACKAGE_NAME = 'reconflux'

async def resolve_appdata_site(prefix: str = '.') -> anyio.Path:
    dirname = f'{prefix}{PACKAGE_NAME}-appdata'
    appdata_path = await filesystem.get_cwd(dirname, resolve=True)
    await appdata_path.mkdir(exist_ok=True)
    if not await appdata_path.is_dir() and os.access(appdata_path, os.W_OK):
        raise AppdataResolutionError(
            f'The resolved appdata site for the application `{appdata_path}`'
            'is not writable. This directory is required for the application '
            'check the permissions of the package.'
        )
    return appdata_path


async def resolve_appdata_file(*parts: str, must_exist: bool = False) -> anyio.Path:
    appdata_path = await resolve_appdata_site()
    path = appdata_path.joinpath(*parts)
    if not await path.is_file() and must_exist:
        raise FileSystemError(
            f'The appdata path that must exist at `{path}` was not'
            'found.'
        )

    return path

async def make_appdata_subdirs(*paths: os.PathLike) -> None:
    appdata_dir = await resolve_appdata_site()

    async def mkdir(path: os.PathLike) -> None:
        await appdata_dir.joinpath(path).mkdir(exist_ok=True)

    await run_concurrently(
        runner=mkdir,
        schedule={f'mkappdata_dir_{path}': path for path in paths},
        fail_fast=True,
    )



class AppDataFile:
    __slots__ = (
        '_contents',
        'path',
    )

    def __init__(self, path: anyio.Path) -> None:
        self.path = path
        self._contents: str | None = None

    @classmethod
    async def resolve(cls, *parts: str, must_exist: bool = False) -> Self:
        path = await resolve_appdata_file(*parts, must_exist=must_exist)
        return cls(path)

    async def exists(self) -> bool:
        return await self.path.exists()

    async def read(self, *, recompute: bool = False) -> str:
        if not recompute and self._contents:
            return self._contents

        with filesystem.wrap_os_error('read appdata file', self.path):
            self._contents = await self.path.read_text()

        return self._contents

    async def write(self, contents: str) -> None:
        with filesystem.wrap_os_error('write appdata file', self.path):
            await self.path.write_text(contents)

    async def write_default(self, contents: str) -> bool:
        """
        Writes the contents to the file if it does not exist

        Parameters
        ----------
        contents : str
            The content to write

        Returns
        ---------
        bool
            True if the file did not exist and the contents
            were written to False if it already existed
        """
        if await self.path.exists():
            return False

        await self.write(contents)
        return True

