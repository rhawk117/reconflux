import dataclasses as dc
from typing import TYPE_CHECKING

import anyio

from reconflux.concurrency import TaskExecutorResult, run_concurrently
from reconflux.core import DataclassMixin
from reconflux.files import FileAnalysisError, FileMetadataReader

if TYPE_CHECKING:
    from collections.abc import Iterable

    from reconflux.files import MetadataResult


@dc.dataclass(slots=True, frozen=True)
class FileAnalysisResult(DataclassMixin):
    """Result for a single file analysis.

    Parameters
    ----------
    path : anyio.Path
        Resolved path of the analyzed file.
    metadata : MetadataResult
        File metadata produced by the matched reader.
    """

    path: anyio.Path
    metadata: MetadataResult

    @property
    def file_name(self) -> str:
        """Return the file's base name."""
        return self.path.name

    @property
    def mime_type(self) -> str | None:
        """Return the detected MIME type."""
        return self.metadata.mime_type

    @property
    def size_kib(self) -> float:
        """Return the file size in kibibytes."""
        return self.metadata.size_kib


@dc.dataclass(slots=True, frozen=True)
class BatchFileAnalysisResult(DataclassMixin):
    """Aggregate result for a multi-file analysis run.

    Parameters
    ----------
    results : TaskExecutorResult[FileAnalysisResult]
        Per-file results and per-file errors keyed by the path string.
    """

    results: TaskExecutorResult[FileAnalysisResult]

    @property
    def succeeded(self) -> list[FileAnalysisResult]:
        """Return successfully analyzed file results."""
        return list(self.results.results.values())

    @property
    def failed(self) -> dict[str, str]:
        """Return a mapping of path strings to error representations."""
        return self.results.errors

    @property
    def total(self) -> int:
        """Return the total number of files attempted."""
        return len(self.results.results) + len(self.results.errors)

    @property
    def okay(self) -> bool:
        """Return whether every file was analyzed without error."""
        return self.results.okay


def _to_anyio_path(path: str | anyio.Path) -> anyio.Path:
    return anyio.Path(path)


@dc.dataclass(slots=True)
class FileAnalysisIntegration:
    """Reconflux file-metadata integration

    Wraps ``FileMetadataAnalyzer`` with a stable integration API that matches
    the pattern of other reconflux integrations. The CLI should talk to this
    class, not directly to the analyzer.

    Parameters
    ----------
    analyzer : FileMetadataAnalyzer | None, default=None
        Configured analyzer. When omitted, ``default_analyzer()`` is used,
        which includes all three built-in readers.
    """

    reader: FileMetadataReader = dc.field(default_factory=FileMetadataReader.create)

    async def analyze(self, path: str | anyio.Path) -> FileAnalysisResult:
        """Analyze a single file and return its metadata.

        Parameters
        ----------
        path : str | anyio.Path
            Path to the file.

        Returns
        -------
        FileAnalysisResult
            Metadata result for the file.

        Raises
        ------
        FileAnalysisError
            If the file does not exist, is not a file, or the reader fails.
        """
        async_path = anyio.Path(path)
        metadata = await self.reader.analyze(async_path)
        return FileAnalysisResult(path=async_path, metadata=metadata)

    async def analyze_many(
        self,
        paths: Iterable[str | anyio.Path],
        *,
        concurrency_limit: int | None = None,
        fail_fast: bool = False,
    ) -> BatchFileAnalysisResult:
        """Analyze multiple files concurrently.

        Parameters
        ----------
        paths : Iterable[str | anyio.Path]
            File paths to analyze.
        concurrency_limit : int | None, default=None
            Maximum number of files analyzed simultaneously. ``None`` means
            no cap.
        fail_fast : bool, default=False
            When ``True``, the first failed analysis cancels remaining tasks.
            When ``False``, errors are collected per-file and the rest
            continue.

        Returns
        -------
        BatchFileAnalysisResult
            Aggregate result containing per-file metadata and any errors.
        """
        schedule: dict[str, anyio.Path] = {str(p): anyio.Path(p) for p in paths}

        async def run_analysis(path: anyio.Path) -> FileAnalysisResult:
            metadata = await self.reader.analyze(path)
            return FileAnalysisResult(path=path, metadata=metadata)

        results = await run_concurrently(
            schedule=schedule,
            runner=run_analysis,
            concurrency_limit=concurrency_limit,
            fail_fast=fail_fast,
        )

        return BatchFileAnalysisResult(results=results)

    async def analyze_directory(
        self,
        directory: str | anyio.Path,
        *,
        glob: str = '*',
        recursive: bool = False,
        concurrency_limit: int | None = None,
        fail_fast: bool = False,
    ) -> BatchFileAnalysisResult:
        """Analyze all files in a directory matching a glob pattern.

        Parameters
        ----------
        directory : str | anyio.Path
            Directory to scan.
        glob : str, default='*'
            Glob pattern applied to the directory contents.
        recursive : bool, default=False
            When ``True``, uses ``**/<glob>`` to recurse into subdirectories.
        concurrency_limit : int | None, default=None
            Maximum number of files analyzed simultaneously.
        fail_fast : bool, default=False
            Whether the first failed analysis should abort sibling tasks.

        Returns
        -------
        BatchFileAnalysisResult
            Aggregate result for every matched file.

        Raises
        ------
        FileAnalysisError
            If the directory does not exist or is not a directory.
        """
        dir_path = _to_anyio_path(directory)

        if not await dir_path.exists():
            raise FileAnalysisError(
                'The requested directory does not exist.',
                context={'directory': str(dir_path)},
            )

        if not await dir_path.is_dir():
            raise FileAnalysisError(
                'The requested path is not a directory.',
                context={'directory': str(dir_path)},
            )

        pattern = f'**/{glob}' if recursive else glob
        paths = [p async for p in dir_path.glob(pattern) if await p.is_file()]

        return await self.analyze_many(
            paths,
            concurrency_limit=concurrency_limit,
            fail_fast=fail_fast,
        )
