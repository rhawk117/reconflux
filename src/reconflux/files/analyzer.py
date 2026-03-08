from __future__ import annotations

import mimetypes
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Self

import anyio
import anyio.to_thread

from reconflux.files.errors import FileAnalysisError
from reconflux.files.models import (
    BaseFileMetadata,
    GenericFileMetadata,
    MetadataResult,
)

if TYPE_CHECKING:
    from reconflux.files.readers import BaseFileReader





def _to_datetime(timestamp: float | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _guess_mime_type(path: Path) -> str | None:
    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type



async def _verify_async_path(async_path: anyio.Path) -> None:
    if not await async_path.exists():
        raise FileAnalysisError(
            'The requested file does not exist.',
            context={'file_path': str(async_path)},
        )

    if not await async_path.is_file():
        raise FileAnalysisError(
            'The requested path is not a file.',
            context={'file_path': str(async_path)},
        )


class FileMetadataAnalyzer:
    __slots__ = (
        '_readers',
    )

    def register_readers(self, *readers: BaseFileReader) -> Self:
        self._readers.update({reader.name: reader for reader in readers})
        return self

    def __init__(self, *readers: BaseFileReader) -> None:
        self._readers: dict[str, BaseFileReader] = {}
        self.register_readers(*readers)

    @property
    def readers(self) -> tuple[BaseFileReader, ...]:
        return tuple(self._readers.values())

    def get_reader(
        self,
        path: Path,
        mime_type: str | None,
    ) -> BaseFileReader | None:
        for reader in self._readers.values():
            if reader.can_read(path, mime_type):
                return reader

        return None

    async def get_base_metadata(self, file_path: Path) -> BaseFileMetadata:
        async_path = anyio.Path(file_path)
        await _verify_async_path(async_path)
        file_stat = await async_path.stat()
        mime_type = _guess_mime_type(file_path)
        created_timestamp = file_stat.st_birthtime
        return BaseFileMetadata(
            path=file_path,
            file_name=file_path.name,
            mime_type=mime_type,
            suffix=file_path.suffix.lower(),
            size_bytes=file_stat.st_size,
            size_kib=file_stat.st_size / 1024,
            created_at=_to_datetime(created_timestamp),
            modified_at=_to_datetime(file_stat.st_mtime),
            accessed_at=_to_datetime(file_stat.st_atime),
            permissions=stat.filemode(file_stat.st_mode),
            is_symlink=await async_path.is_symlink(),
        )


    async def analyze(
        self,
        file_path: str | Path,
    ) -> MetadataResult:
        path = Path(file_path)
        base_metadata = await self.get_base_metadata(path)

        reader = self.get_reader(path, base_metadata.mime_type)
        if reader is None:
            return GenericFileMetadata(**base_metadata.asdict())

        try:
            return await anyio.to_thread.run_sync(
                reader.read,
                path,
                base_metadata.mime_type,
                base_metadata,
            )
        except Exception as exc:
            raise FileAnalysisError(
                'The file reader failed to analyze the file.',
                context={
                    'file_path': str(path),
                    'reader': getattr(reader, 'name', reader.__class__.__name__),
                    'mime_type': base_metadata.mime_type,
                },
            ) from exc
