from __future__ import annotations

import dataclasses as dc
from typing import TYPE_CHECKING

import anyio

from rich.table import Table

from reconflux.core import DataclassMixin

if TYPE_CHECKING:
    from datetime import datetime


def _stringify(value: object) -> str:
    if value is None:
        return ''
    return str(value)


class RichMetadataMixin:
    section_title: str = 'Metadata'

    def summary_rows(self) -> list[tuple[str, str]]:
        raise NotImplementedError

    def detail_tables(self) -> list[Table]:
        return []

    def as_table(self) -> Table:
        table = Table(title=self.section_title)
        table.add_column('Field', style='bold cyan', no_wrap=True)
        table.add_column('Value', overflow='fold')

        for key, value in self.summary_rows():
            table.add_row(key, value)

        return table

    def __rich__(self) -> Table:
        return self.as_table()


@dc.dataclass(slots=True)
class BaseFileMetadata(RichMetadataMixin, DataclassMixin):
    path: anyio.Path
    file_name: str
    mime_type: str | None
    suffix: str
    size_bytes: int
    size_kib: float
    created_at: datetime | None
    modified_at: datetime | None
    accessed_at: datetime | None
    permissions: str
    is_symlink: bool = False
    section_title: str = 'File Metadata'

    def summary_rows(self) -> list[tuple[str, str]]:
        return [
            ('Path', str(self.path)),
            ('File Name', self.file_name),
            ('MIME Type', _stringify(self.mime_type)),
            ('Suffix', self.suffix),
            ('Size (bytes)', str(self.size_bytes)),
            ('Size (KiB)', f'{self.size_kib:.2f}'),
            ('Created', _stringify(self.created_at)),
            ('Modified', _stringify(self.modified_at)),
            ('Accessed', _stringify(self.accessed_at)),
            ('Permissions', self.permissions),
            ('Symlink', str(self.is_symlink)),
        ]


class GenericFileMetadata(BaseFileMetadata):
    pass


@dc.dataclass(slots=True)
class ImageMetadata(BaseFileMetadata):
    width: int | None = None
    height: int | None = None
    image_format: str | None = None
    image_mode: str | None = None
    exif: dict[str, str] = dc.field(default_factory=dict)

    def summary_rows(self) -> list[tuple[str, str]]:
        rows = super().summary_rows()
        rows.extend([
            ('Image Format', _stringify(self.image_format)),
            ('Image Mode', _stringify(self.image_mode)),
            ('Width', _stringify(self.width)),
            ('Height', _stringify(self.height)),
        ])
        return rows


@dc.dataclass(slots=True)
class PDFMetadata(BaseFileMetadata):
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    creator: str | None = None
    producer: str | None = None
    page_count: int | None = None
    is_encrypted: bool = False
    extra: dict[str, str] = dc.field(default_factory=dict)

    def summary_rows(self) -> list[tuple[str, str]]:
        rows = super().summary_rows()
        rows.extend([
            ('Title', _stringify(self.title)),
            ('Author', _stringify(self.author)),
            ('Subject', _stringify(self.subject)),
            ('Creator', _stringify(self.creator)),
            ('Producer', _stringify(self.producer)),
            ('Page Count', _stringify(self.page_count)),
            ('Encrypted', str(self.is_encrypted)),
        ])
        return rows


@dc.dataclass(slots=True)
class SpreadsheetMetadata(BaseFileMetadata):
    title: str | None = None
    creator: str | None = None
    keywords: str | None = None
    description: str | None = None
    category: str | None = None
    last_modified_by: str | None = None
    created: datetime | None = None
    modified: datetime | None = None

    def summary_rows(self) -> list[tuple[str, str]]:
        rows = super().summary_rows()
        rows.extend([
            ('Title', _stringify(self.title)),
            ('Creator', _stringify(self.creator)),
            ('Keywords', _stringify(self.keywords)),
            ('Description', _stringify(self.description)),
            ('Category', _stringify(self.category)),
            ('Last Modified By', _stringify(self.last_modified_by)),
            ('Created', _stringify(self.created)),
            ('Modified', _stringify(self.modified)),
        ])
        return rows


type MetadataResult = (
    GenericFileMetadata | ImageMetadata | PDFMetadata | SpreadsheetMetadata
)
