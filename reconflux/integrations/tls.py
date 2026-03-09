from __future__ import annotations

import dataclasses as dc
from typing import TYPE_CHECKING

import anyio.to_thread

from reconflux.concurrency import TaskExecutorResult, run_concurrently
from reconflux.core import DataclassMixin
from reconflux.net.tls import (
    TLSCertificateResult,
    TLSClientOptions,
    fetch_tls_certificate_sync,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


@dc.dataclass(slots=True, frozen=True)
class TLSBatchResult(DataclassMixin):
    """Aggregate result for a multi-host TLS certificate fetch.

    Parameters
    ----------
    results : TaskExecutorResult[TLSCertificateResult]
        Per-hostname certificate results and errors, keyed by hostname.
    """

    results: TaskExecutorResult[TLSCertificateResult]

    @property
    def succeeded(self) -> list[TLSCertificateResult]:
        """Return certificates that were fetched successfully."""
        return list(self.results.results.values())

    @property
    def failed(self) -> dict[str, str]:
        """Return a mapping of hostname to error representation."""
        return self.results.errors

    @property
    def total(self) -> int:
        """Return the total number of hosts attempted."""
        return len(self.results.results) + len(self.results.errors)

    @property
    def okay(self) -> bool:
        """Return whether every fetch completed without error."""
        return self.results.okay


@dc.dataclass(slots=True)
class TLSIntegration:
    """Reconflux TLS certificate integration service.

    Wraps the synchronous ``fetch_tls_certificate_sync`` function, running it
    in a thread pool so it fits into the async-first integration model. Supports
    single and concurrent multi-host certificate fetches.

    Parameters
    ----------
    options : TLSClientOptions | None, default=None
        Default client options (port, timeout, verify). When omitted,
        ``TLSClientOptions()`` is used (port 443, 10 s timeout, verify=True).
    """

    options: TLSClientOptions = dc.field(default_factory=TLSClientOptions)

    async def fetch(self, hostname: str) -> TLSCertificateResult:
        """Fetch the TLS certificate for a single hostname.

        The underlying socket I/O is blocking, so this method delegates to
        ``anyio.to_thread.run_sync`` to avoid stalling the event loop.

        Parameters
        ----------
        hostname : str
            Host to inspect.

        Returns
        -------
        TLSCertificateResult
            Parsed certificate details.

        Raises
        ------
        TLSCertificateError
            On SSL errors, connection timeouts, or socket-level failures.
        """
        return await anyio.to_thread.run_sync(
            fetch_tls_certificate_sync,
            hostname,
            self.options,
        )

    async def fetch_many(
        self,
        hostnames: Iterable[str],
        *,
        concurrency_limit: int | None = None,
        fail_fast: bool = False,
    ) -> TLSBatchResult:
        """Fetch TLS certificates for multiple hosts concurrently.

        Parameters
        ----------
        hostnames : Iterable[str]
            Hosts to inspect.
        concurrency_limit : int | None, default=None
            Maximum number of simultaneous certificate fetches. ``None`` means
            no cap.
        fail_fast : bool, default=False
            When ``True``, the first failed fetch cancels remaining tasks.
            When ``False``, errors are collected per-host and the rest
            continue.

        Returns
        -------
        TLSBatchResult
            Aggregate result with per-host certificates and any errors.
        """
        schedule = {hostname: hostname for hostname in hostnames}

        async def run_fetch(hostname: str) -> TLSCertificateResult:
            return await self.fetch(hostname)

        results = await run_concurrently(
            schedule=schedule,
            runner=run_fetch,
            concurrency_limit=concurrency_limit,
            fail_fast=fail_fast,
        )

        return TLSBatchResult(results=results)
