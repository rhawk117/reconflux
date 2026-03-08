from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import ExifTags, Image

from reconflux.fs.models import ImageMetadata
import openpyxl

if TYPE_CHECKING:
    from pathlib import Path

    from reconflux.fs.models import BaseFileMetadata, MetadataResult



class BaseFileReader:
    name = 'base'

    def can_read(
        self,
        path: Path,
        mime_type: str | None,
    ) -> bool:
        raise NotImplementedError

    def read(
        self,
        path: Path,
        *,
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
        path: Path,
        mime_type: str | None,
    ) -> bool:
        if path.suffix.lower() in self._supported_suffixes:
            return True

        return bool(mime_type and mime_type.startswith('image/'))

    def read(
        self,
        path: Path,
        *,
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


