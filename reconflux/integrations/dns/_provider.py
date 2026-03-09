from __future__ import annotations

from typing import TYPE_CHECKING

import dns.resolver

from reconflux.concurrency import run_concurrently
from reconflux.integrations.dns import EmailDNSResult
from reconflux.integrations.dns._models import (
    CanonicalNameResult,
    DNSBlocklist,
    DNSBlocklistCollectionResult,
    DNSBlocklistResult,
    DNSIntegrationResult,
    DNSLookupKind,
    DNSLookupRequest,
    DomainDNSResult,
    HostDNSResult,
    ReverseDNSResult,
)
from reconflux.net.dns import (
    DNSClient,
    DNSClientOptions,
    DNSQueryResult,
    DNSRecordType,
    ReverseLookupResult,
)
from reconflux.net.dns._errors import DNSResolutionError, ReverseLookupError

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


def get_default_blocklist() -> set[str]:
    """Return the default DNS blocklist zones.

    Returns
    -------
    set[str]
        The default blocklist zones used for DNSBL lookups.
    """
    return {
        'zen.spamhaus.org',
        'bl.spamcop.net',
        'dnsbl.sorbs.net',
        'b.barracudacentral.org',
    }


def get_default_record_types() -> tuple[DNSRecordType, ...]:
    """Return the default domain-sweep record types.

    PTR is intentionally excluded here because PTR is a reverse-DNS concern for
    IP lookups rather than a normal domain inspection path.

    Returns
    -------
    tuple[DNSRecordType, ...]
        Default forward-query record types.
    """
    return tuple(DNSRecordType)


def normalize_email_domain(email_address: str) -> str:
    """Extract and normalize the domain portion of an email address.

    Parameters
    ----------
    email_address : str
        Email address to parse.

    Returns
    -------
    str
        Lowercased email domain.

    Raises
    ------
    ValueError
        If the email address is malformed.
    """
    _, separator, domain = email_address.strip().partition('@')
    if separator != '@' or not domain:
        raise ValueError(f'Invalid email address: {email_address!r}')

    return domain.lower()


class DNSProvider:
    """Reconflux DNS integration service.

    This class provides stable, TUI-friendly use cases over the lower-level
    DNS client. The CLI should talk to this integration, not directly to the
    client.

    Parameters
    ----------
    client : DNSClient | None, default=None
        DNS client instance. If omitted, a new client is created.
    client_options : DNSClientOptions | None, default=None
        DNS client options used when creating an implicit client.
    default_blocklists : Iterable[DNSBlocklist] | None, default=None
        Blocklists to use for DNSBL lookups when none are supplied explicitly.
    """

    def __init__(
        self,
        *,
        client: DNSClient | None = None,
        client_options: DNSClientOptions | None = None,
        default_blocklists: Iterable[DNSBlocklist] | None = None,
    ) -> None:
        self._client = client or DNSClient(options=client_options)
        self._default_blocklists = tuple(
            default_blocklists
            if default_blocklists is not None
            else (
                DNSBlocklist(zone=zone_name)
                for zone_name in sorted(get_default_blocklist())
            )
        )

    @property
    def client(self) -> DNSClient:
        """Return the underlying DNS client.

        Returns
        -------
        DNSClient
            The configured DNS client.
        """
        return self._client

    @property
    def default_blocklists(self) -> tuple[DNSBlocklist, ...]:
        """Return the default blocklists.

        Returns
        -------
        tuple[DNSBlocklist, ...]
            Default DNSBL definitions.
        """
        return self._default_blocklists

    async def dispatch(
        self,
        request: DNSLookupRequest,
        *,
        search: bool | None = None,
        tcp: bool = False,
        include_blocklists: bool = True,
        record_types: Sequence[DNSRecordType | str] | None = None,
    ) -> DNSIntegrationResult:
        """Dispatch a top-level DNS lookup request.

        Parameters
        ----------
        request : DNSLookupRequest
            Domain, IP, or email lookup request.
        search : bool | None, default=None
            Resolver search-domain behavior override.
        tcp : bool, default=False
            Whether to force TCP for record queries.
        include_blocklists : bool, default=True
            Whether to perform DNSBL lookups for IP-address requests.
        record_types : Sequence[DNSRecordType | str] | None, default=None
            Optional record types for domain sweeps.

        Returns
        -------
        DNSIntegrationResult
            Typed result object corresponding to the request kind.
        """
        if request.kind is DNSLookupKind.DOMAIN and request.domain:
            return await self.lookup_domain(
                request.domain,
                search=search,
                tcp=tcp,
                record_types=record_types,
            )

        if request.kind is DNSLookupKind.IP_ADDRESS:
            return await self.lookup_ip_address(
                request.ip_address,  # type: ignore
                search=search,
                include_blocklists=include_blocklists,
            )

        return await self.lookup_email(
            request.email,  # type: ignore
            search=search,
            tcp=tcp,
        )

    async def lookup_domain(
        self,
        domain: str,
        *,
        search: bool | None = None,
        tcp: bool = False,
        record_types: Sequence[DNSRecordType | str] | None = None,
        fail_fast: bool = False,
    ) -> DomainDNSResult:
        """Resolve a domain across the default record sweep.

        Parameters
        ----------
        domain : str
            Domain to inspect.
        search : bool | None, default=None
            Resolver search-domain behavior override.
        tcp : bool, default=False
            Whether to force TCP for record queries.
        record_types : Sequence[DNSRecordType | str] | None, default=None
            Record types to query. If omitted, the default domain-sweep set is
            used.
        fail_fast : bool, default=False
            Whether the first failed record query should abort sibling queries.

        Returns
        -------
        DomainDNSResult
            Aggregated domain DNS result.
        """
        effective_record_types = tuple(record_types or get_default_record_types())
        schedule = {
            str(record_type): str(record_type) for record_type in effective_record_types
        }

        async def run_record_query(record_type: str) -> DNSQueryResult:
            return await self.client.resolve(
                domain,
                record_type=record_type,
                search=search,
                tcp=tcp,
            )

        query_results = await run_concurrently(
            schedule=schedule,
            runner=run_record_query,
            fail_fast=fail_fast,
        )

        return DomainDNSResult(
            domain=domain,
            queries=query_results,
        )

    async def lookup_ip_address(
        self,
        ip_address: str,
        *,
        search: bool | None = None,
        include_blocklists: bool = True,
    ) -> ReverseDNSResult:
        """Perform reverse lookup for an IP address.

        Parameters
        ----------
        ip_address : str
            IP address to inspect.
        search : bool | None, default=None
            Resolver search-domain behavior override.
        include_blocklists : bool, default=True
            Whether to also perform DNSBL checks.

        Returns
        -------
        ReverseDNSResult
            Reverse-lookup result, optionally including blocklist data.
        """
        reverse_lookup_result: ReverseLookupResult | None = None
        reverse_lookup_error: str | None = None

        try:
            reverse_lookup_result = await self.client.resolve_address(
                ip_address,
                search=search,
            )
        except ReverseLookupError as exc:
            reverse_lookup_error = repr(exc)

        blocklist_result: DNSBlocklistCollectionResult | None = None
        if include_blocklists:
            blocklist_result = await self.lookup_blocklists(ip_address)

        return ReverseDNSResult(
            ip_address=ip_address,
            reverse_lookup=reverse_lookup_result,
            error=reverse_lookup_error,
            blocklists=blocklist_result,
        )

    async def lookup_email(
        self,
        email_address: str,
        *,
        search: bool | None = None,
        tcp: bool = False,
        fail_fast: bool = False,
    ) -> EmailDNSResult:
        """Inspect an email address via MX, TXT, and DMARC-related queries.

        Parameters
        ----------
        email_address : str
            Email address to inspect.
        search : bool | None, default=None
            Resolver search-domain behavior override.
        tcp : bool, default=False
            Whether to force TCP for record queries.
        fail_fast : bool, default=False
            Whether the first failed query should abort sibling queries.

        Returns
        -------
        EmailDNSResult
            Aggregated email-related DNS inspection result.
        """
        email_domain = normalize_email_domain(email_address)
        schedule = {
            'MX': (email_domain, DNSRecordType.MX),
            'TXT': (email_domain, DNSRecordType.TXT),
            'DMARC': (f'_dmarc.{email_domain}', DNSRecordType.TXT),
        }

        async def run_email_query(
            payload: tuple[str, DNSRecordType],
        ) -> DNSQueryResult:
            query_name, record_type = payload
            return await self.client.resolve(
                query_name,
                record_type=record_type,
                search=search,
                tcp=tcp,
            )

        query_results = await run_concurrently(
            schedule=schedule,
            runner=run_email_query,
            fail_fast=fail_fast,
        )

        return EmailDNSResult(
            email=email_address,
            domain=email_domain,
            queries=query_results,
        )

    async def lookup_blocklists(
        self,
        ip_address: str,
        *,
        blocklists: Iterable[DNSBlocklist] | None = None,
        fail_fast: bool = False,
    ) -> DNSBlocklistCollectionResult:
        """Check an IP address against multiple DNS blocklists.

        Parameters
        ----------
        ip_address : str
            IP address to inspect.
        blocklists : Iterable[DNSBlocklist] | None, default=None
            Blocklists to query. Defaults to the integration's configured set.
        fail_fast : bool, default=False
            Whether the first failed blocklist query should abort siblings.

        Returns
        -------
        DNSBlocklistCollectionResult
            Aggregate blocklist lookup result.
        """
        effective_blocklists = tuple(blocklists or self.default_blocklists)
        schedule = {blocklist.zone: blocklist for blocklist in effective_blocklists}

        async def run_blocklist_lookup(
            blocklist: DNSBlocklist,
        ) -> DNSBlocklistResult:
            return await self._lookup_single_blocklist(ip_address, blocklist)

        lookup_results = await run_concurrently(
            schedule=schedule,
            runner=run_blocklist_lookup,
            fail_fast=fail_fast,
        )

        return DNSBlocklistCollectionResult(
            ip_address=ip_address,
            results=lookup_results,
        )

    async def resolve_host(
        self,
        hostname: str,
        *,
        search: bool | None = None,
    ) -> HostDNSResult:
        """Resolve A and AAAA addresses for a hostname.

        Parameters
        ----------
        hostname : str
            Hostname to resolve.
        search : bool | None, default=None
            Resolver search-domain behavior override.

        Returns
        -------
        HostDNSResult
            Wrapped host-address result.
        """
        host_resolution = await self.client.resolve_name(
            hostname,
            search=search,
        )
        return HostDNSResult(
            hostname=hostname,
            resolution=host_resolution,
        )

    async def resolve_canonical_name(self, hostname: str) -> CanonicalNameResult:
        """Resolve the canonical DNS name for a hostname.

        Parameters
        ----------
        hostname : str
            Hostname to inspect.

        Returns
        -------
        CanonicalNameResult
            Wrapped canonical-name result.
        """
        canonical_name = await self.client.canonical_name(hostname)
        return CanonicalNameResult(
            hostname=hostname,
            canonical_name=canonical_name,
        )

    async def _lookup_single_blocklist(
        self,
        ip_address: str,
        blocklist: DNSBlocklist,
    ) -> DNSBlocklistResult:
        """Perform one DNSBL lookup.

        Parameters
        ----------
        ip_address : str
            IP address to inspect.
        blocklist : DNSBlocklist
            Blocklist definition.

        Returns
        -------
        DNSBlocklistResult
            Result for the individual blocklist query.
        """
        query_name = blocklist.query_name(ip_address)

        try:
            query_result = await self.client.resolve(
                query_name,
                record_type=DNSRecordType.A,
                raise_on_no_answer=False,
            )
        except DNSResolutionError as exc:
            cause = exc.__cause__

            if isinstance(cause, (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer)):
                return DNSBlocklistResult(
                    ip_address=ip_address,
                    blocklist=blocklist,
                    query_name=query_name,
                    listed=False,
                    records=[],
                    error=None,
                )

            return DNSBlocklistResult(
                ip_address=ip_address,
                blocklist=blocklist,
                query_name=query_name,
                listed=None,
                records=[],
                error=repr(exc),
            )

        return DNSBlocklistResult(
            ip_address=ip_address,
            blocklist=blocklist,
            query_name=query_name,
            listed=not query_result.is_empty,
            records=[record.value for record in query_result.records],
            error=None,
        )
