from __future__ import annotations

from typing import TYPE_CHECKING

import anyio
import openpyxl
from PIL import ExifTags, Image
from pypdf import PdfReader

from reconflux.files._models import ImageMetadata, PDFMetadata, SpreadsheetMetadata

if TYPE_CHECKING:
    from reconflux.files._models import BaseFileMetadata, MetadataResult


class BaseFileReader:
    name = 'base'

    def can_read(
        self,
        path: anyio.Path,
        mime_type: str | None,
    ) -> bool:
        raise NotImplementedError

    def read(
        self,
        path: anyio.Path,
        mime_type: str | None,
        base_metadata: BaseFileMetadata,
    ) -> MetadataResult:
        raise NotImplementedError


class ImageReader(BaseFileReader):
    name = 'image'
    _supported_suffixes = {
        '.jpg',
        '.jpeg',
        '.png',
        '.tif',
        '.tiff',
        '.bmp',
        '.gif',
        '.webp',
    }

    def can_read(
        self,
        path: anyio.Path,
        mime_type: str | None,
    ) -> bool:
        if path.suffix.lower() in self._supported_suffixes:
            return True

        return bool(mime_type and mime_type.startswith('image/'))

    def read(
        self,
        path: anyio.Path,
        mime_type: str | None,
        base_metadata: BaseFileMetadata,
    ) -> ImageMetadata:
        with Image.open(path) as image:
            exif: dict[str, str] = {}
            raw_exif = image.getexif()

            if raw_exif:
                tag_names = {tag.value: tag.name for tag in ExifTags.Base}

                for key, value in raw_exif.items():
                    tag_name = tag_names.get(key, str(key))
                    exif[tag_name] = self._normalize_value(value)

            return ImageMetadata(
                **base_metadata.asdict(),
                width=image.width,
                height=image.height,
                image_format=image.format,
                image_mode=image.mode,
                exif=exif,
            )

    @staticmethod
    def _normalize_value(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode('utf-8', errors='replace')
        return str(value)


class SpreadsheetReader(BaseFileReader):
    name = 'spreadsheet'
    _supported_suffixes = {'.xlsx', '.xlsm'}

    def can_read(
        self,
        path: anyio.Path,
        mime_type: str | None,
    ) -> bool:
        return path.suffix.lower() in self._supported_suffixes

    def read(
        self,
        path: anyio.Path,
        mime_type: str | None,
        base_metadata: BaseFileMetadata,
    ) -> SpreadsheetMetadata:
        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
        properties = workbook.properties

        return SpreadsheetMetadata(
            **base_metadata.asdict(),
            title=properties.title,
            creator=properties.creator,
            keywords=properties.keywords,
            description=properties.description,
            category=properties.category,
            last_modified_by=properties.lastModifiedBy,
            created=properties.created,
            modified=properties.modified,
        )


def _to_optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


class PDFReader(BaseFileReader):
    name = 'pdf'

    def can_read(
        self,
        path: anyio.Path,
        mime_type: str | None,
    ) -> bool:
        return path.suffix.lower() == '.pdf' or mime_type == 'application/pdf'

    def read(
        self,
        path: anyio.Path,
        mime_type: str | None,
        base_metadata: BaseFileMetadata,
    ) -> PDFMetadata:
        # Use the builtin open() rather than path.open() because this method
        # runs inside anyio.to_thread.run_sync and anyio.Path.open() is async.
        with open(path, 'rb') as file_handle:  # noqa: PTH123
            reader = PdfReader(file_handle)
            metadata = reader.metadata

            extra: dict[str, str] = {}
            if metadata:
                extra = {str(key): str(value) for key, value in metadata.items()}

            return PDFMetadata(
                **base_metadata.asdict(),
                title=_to_optional_str(getattr(metadata, 'title', None)),
                author=_to_optional_str(getattr(metadata, 'author', None)),
                subject=_to_optional_str(getattr(metadata, 'subject', None)),
                creator=_to_optional_str(getattr(metadata, 'creator', None)),
                producer=_to_optional_str(getattr(metadata, 'producer', None)),
                page_count=len(reader.pages),
                is_encrypted=reader.is_encrypted,
                extra=extra,
            )
