from __future__ import annotations

import dataclasses as dc
import mimetypes
import stat
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

import anyio
import anyio.to_thread

from reconflux.files._errors import FileAnalysisError
from reconflux.files._models import (
    BaseFileMetadata,
    GenericFileMetadata,
    MetadataResult,
)
from reconflux.files._readers import (
    BaseFileReader,
    ImageReader,
    PDFReader,
    SpreadsheetReader,
)

if TYPE_CHECKING:
    from reconflux.files._readers import BaseFileReader


def _to_datetime(timestamp: float | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _guess_mime_type(path: anyio.Path) -> str | None:
    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type


async def _verify_path(path: anyio.Path) -> None:
    if not await path.exists():
        raise FileAnalysisError(
            'The requested file does not exist.',
            context={'file_path': str(path)},
        )

    if not await path.is_file():
        raise FileAnalysisError(
            'The requested path is not a file.',
            context={'file_path': str(path)},
        )


@dc.dataclass(slots=True)
class FileMetadataReader:
    _readers: dict[str, BaseFileReader] = dc.field(init=False)

    def register(self, *readers: BaseFileReader) -> Self:
        self._readers.update({reader.name: reader for reader in readers})
        return self

    def register_builtins(self) -> Self:
        return self.register(
            ImageReader(),
            PDFReader(),
            SpreadsheetReader(),
        )

    @classmethod
    def create(cls, *readers: BaseFileReader, builtins_okay: bool = True) -> Self:
        this = cls()
        if builtins_okay:
            this.register_builtins()

        if readers:
            this.register(*readers)

        return this

    def get_reader(
        self,
        path: anyio.Path,
        mime_type: str | None,
    ) -> BaseFileReader | None:
        for reader in self._readers.values():
            if reader.can_read(path, mime_type):
                return reader

        return None

    @property
    def readers(self) -> tuple[BaseFileReader, ...]:
        return tuple(self._readers.values())

    async def get_base_metadata(self, path: anyio.Path) -> BaseFileMetadata:
        await _verify_path(path)
        file_stat = await path.stat()
        mime_type = _guess_mime_type(path)
        created_timestamp = getattr(file_stat, 'st_birthtime', None)
        return BaseFileMetadata(
            path=path,
            file_name=path.name,
            mime_type=mime_type,
            suffix=path.suffix.lower(),
            size_bytes=file_stat.st_size,
            size_kib=file_stat.st_size / 1024,
            created_at=_to_datetime(created_timestamp),
            modified_at=_to_datetime(file_stat.st_mtime),
            accessed_at=_to_datetime(file_stat.st_atime),
            permissions=stat.filemode(file_stat.st_mode),
            is_symlink=await path.is_symlink(),
        )

    async def analyze(self, path: str | anyio.Path) -> MetadataResult:
        async_path = anyio.Path(path)
        base_metadata = await self.get_base_metadata(async_path)

        reader = self.get_reader(async_path, base_metadata.mime_type)
        if reader is None:
            return GenericFileMetadata(**base_metadata.asdict())

        try:
            return await anyio.to_thread.run_sync(
                reader.read,
                async_path,
                base_metadata.mime_type,
                base_metadata,
            )
        except Exception as exc:
            raise FileAnalysisError(
                'The file reader failed to analyze the file.',
                context={
                    'file_path': str(async_path),
                    'reader': getattr(reader, 'name', reader.__class__.__name__),
                    'mime_type': base_metadata.mime_type,
                },
            ) from exc
