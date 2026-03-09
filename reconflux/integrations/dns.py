from __future__ import annotations

import dataclasses as dc
import ipaddress
from enum import StrEnum
from typing import TYPE_CHECKING

import dns.resolver

from reconflux.concurrency import TaskExecutorResult, run_concurrently
from reconflux.core import DataclassMixin
from reconflux.net.dns import (
    DNSClient,
    DNSClientOptions,
    DNSQueryResult,
    DNSRecordType,
    HostResolutionResult,
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


class DNSLookupKind(StrEnum):
    """Supported top-level DNS lookup modes."""

    DOMAIN = 'domain'
    IP_ADDRESS = 'ip_address'
    EMAIL = 'email'


@dc.dataclass(slots=True, frozen=True)
class DNSLookupRequest(DataclassMixin):
    """Dispatch request for the DNS integration.

    Exactly one of ``domain``, ``ip_address``, or ``email`` must be provided.

    Parameters
    ----------
    domain : str | None, default=None
        Domain name to inspect.
    ip_address : str | None, default=None
        IP address to reverse-resolve and optionally check against blocklists.
    email : str | None, default=None
        Email address to inspect via MX/TXT/DMARC-related queries.
    """

    domain: str | None = None
    ip_address: str | None = None
    email: str | None = None

    def __post_init__(self) -> None:
        populated_fields = [
            field_value
            for field_value in (self.domain, self.ip_address, self.email)
            if field_value is not None
        ]
        if len(populated_fields) != 1:
            raise ValueError(
                'Exactly one of domain, ip_address, or email must be provided.'
            )

    @property
    def kind(self) -> DNSLookupKind:
        """Return the request kind.

        Returns
        -------
        DNSLookupKind
            The request discriminator.
        """
        if self.domain is not None:
            return DNSLookupKind.DOMAIN
        if self.ip_address is not None:
            return DNSLookupKind.IP_ADDRESS
        return DNSLookupKind.EMAIL


@dc.dataclass(slots=True, frozen=True)
class DNSRecordRow(DataclassMixin):
    """Flat row representation for DNS records.

    Parameters
    ----------
    query_name : str
        Query name that was resolved.
    record_type : str
        DNS record type.
    value : str
        Resolved record value.
    ttl : int | None, default=None
        Record TTL.
    canonical_name : str | None, default=None
        Canonical name returned by the resolver.
    nameserver : str | None, default=None
        Responding nameserver.
    port : int | None, default=None
        Nameserver port.
    response_time_ms : float | None, default=None
        Query response time in milliseconds.
    """

    query_name: str
    record_type: str
    value: str
    ttl: int | None = None
    canonical_name: str | None = None
    nameserver: str | None = None
    port: int | None = None
    response_time_ms: float | None = None


@dc.dataclass(slots=True, frozen=True)
class ReverseLookupRow(DataclassMixin):
    """Flat row representation for reverse lookup results.

    Parameters
    ----------
    ip_address : str
        Queried IP address.
    hostname : str
        Reverse-resolved hostname.
    """

    ip_address: str
    hostname: str


@dc.dataclass(slots=True, frozen=True)
class DNSBlocklist(DataclassMixin):
    """DNS blocklist definition.

    Parameters
    ----------
    zone : str
        DNSBL zone name.
    description : str | None, default=None
        Optional human-readable description.
    """

    zone: str
    description: str | None = None

    def query_name(self, ip_address: str) -> str:
        """Build the DNSBL lookup name for an IP address.

        Parameters
        ----------
        ip_address : str
            IPv4 or IPv6 address to test.

        Returns
        -------
        str
            DNSBL query name.
        """
        normalized_ip = ipaddress.ip_address(ip_address)

        if isinstance(normalized_ip, ipaddress.IPv4Address):
            reversed_octets = '.'.join(reversed(ip_address.split('.')))
            return f'{reversed_octets}.{self.zone}'

        exploded_hex = normalized_ip.exploded.replace(':', '')
        reversed_nibbles = '.'.join(reversed(exploded_hex))
        return f'{reversed_nibbles}.{self.zone}'


@dc.dataclass(slots=True, frozen=True)
class DNSBlocklistResult(DataclassMixin):
    """Result for a single blocklist lookup.

    Parameters
    ----------
    ip_address : str
        Inspected IP address.
    blocklist : DNSBlocklist
        Blocklist that was queried.
    query_name : str
        Generated DNSBL query name.
    listed : bool | None
        ``True`` if listed, ``False`` if not listed, ``None`` if unknown due to
        an actual query failure.
    records : list[str]
        Returned DNSBL records if listed.
    error : str | None, default=None
        Error string when the lookup failed for reasons other than normal
        absence from the blocklist.
    """

    ip_address: str
    blocklist: DNSBlocklist
    query_name: str
    listed: bool | None
    records: list[str]
    error: str | None = None

    @property
    def okay(self) -> bool:
        """Return whether the lookup completed without an integration error.

        Returns
        -------
        bool
            ``True`` when the lookup produced either listed or not-listed
            output without an unexpected failure.
        """
        return self.error is None


@dc.dataclass(slots=True, frozen=True)
class DNSBlocklistCollectionResult(DataclassMixin):
    """Aggregate result for multiple DNSBL lookups.

    Parameters
    ----------
    ip_address : str
        Inspected IP address.
    results : TaskExecutorResult[DNSBlocklistResult]
        Per-blocklist lookup results.
    """

    ip_address: str
    results: TaskExecutorResult[DNSBlocklistResult]

    @property
    def listed(self) -> list[DNSBlocklistResult]:
        """Return blocklists that reported the IP as listed."""
        return [
            result for result in self.results.results.values() if result.listed is True
        ]

    @property
    def not_listed(self) -> list[DNSBlocklistResult]:
        """Return blocklists that reported the IP as not listed."""
        return [
            result for result in self.results.results.values() if result.listed is False
        ]

    @property
    def unknown(self) -> list[DNSBlocklistResult]:
        """Return blocklists whose status could not be determined."""
        return [
            result for result in self.results.results.values() if result.listed is None
        ]


@dc.dataclass(slots=True, frozen=True)
class DomainDNSResult(DataclassMixin):
    """Aggregate domain inspection result.

    Parameters
    ----------
    domain : str
        Inspected domain.
    queries : TaskExecutorResult[DNSQueryResult]
        Per-record-type DNS query results.
    """

    domain: str
    queries: TaskExecutorResult[DNSQueryResult]

    @property
    def rows(self) -> list[DNSRecordRow]:
        """Flatten all successful record answers into table rows.

        Returns
        -------
        list[DNSRecordRow]
            Flat rows suitable for TUI rendering.
        """
        flattened_rows: list[DNSRecordRow] = []

        for query_result in self.queries.results.values():
            flattened_rows.extend(
                DNSRecordRow(
                    query_name=query_result.query_name,
                    record_type=str(query_result.record_type),
                    value=answer_record.value,
                    ttl=answer_record.ttl,
                    canonical_name=query_result.canonical_name,
                    nameserver=query_result.nameserver,
                    port=query_result.port,
                    response_time_ms=query_result.response_time_ms,
                )
                for answer_record in query_result.records
            )

        return flattened_rows


@dc.dataclass(slots=True, frozen=True)
class ReverseDNSResult(DataclassMixin):
    """Aggregate reverse-lookup result.

    Parameters
    ----------
    ip_address : str
        Inspected IP address.
    reverse_lookup : ReverseLookupResult | None
        Reverse lookup result when successful.
    error : str | None, default=None
        Error string when reverse lookup failed.
    blocklists : DNSBlocklistCollectionResult | None, default=None
        Optional blocklist lookup results.
    """

    ip_address: str
    reverse_lookup: ReverseLookupResult | None
    error: str | None = None
    blocklists: DNSBlocklistCollectionResult | None = None

    @property
    def rows(self) -> list[ReverseLookupRow]:
        """Flatten reverse lookup hostnames into table rows.

        Returns
        -------
        list[ReverseLookupRow]
            Flat rows suitable for TUI rendering.
        """
        if self.reverse_lookup is None:
            return []

        return [
            ReverseLookupRow(
                ip_address=self.reverse_lookup.ip_address,
                hostname=hostname,
            )
            for hostname in self.reverse_lookup.hostnames
        ]


@dc.dataclass(slots=True, frozen=True)
class EmailDNSResult(DataclassMixin):
    """Aggregate email-related DNS inspection result.

    Parameters
    ----------
    email : str
        Original email address.
    domain : str
        Extracted email domain.
    queries : TaskExecutorResult[DNSQueryResult]
        DNS query results for MX, TXT, and DMARC-related lookups.
    """

    email: str
    domain: str
    queries: TaskExecutorResult[DNSQueryResult]

    @property
    def rows(self) -> list[DNSRecordRow]:
        """Flatten successful DNS answers into table rows.

        Returns
        -------
        list[DNSRecordRow]
            Flat rows suitable for TUI rendering.
        """
        flattened_rows: list[DNSRecordRow] = []

        for query_result in self.queries.results.values():
            flattened_rows.extend(
                DNSRecordRow(
                    query_name=query_result.query_name,
                    record_type=str(query_result.record_type),
                    value=answer_record.value,
                    ttl=answer_record.ttl,
                    canonical_name=query_result.canonical_name,
                    nameserver=query_result.nameserver,
                    port=query_result.port,
                    response_time_ms=query_result.response_time_ms,
                )
                for answer_record in query_result.records
            )

        return flattened_rows


@dc.dataclass(slots=True, frozen=True)
class HostDNSResult(DataclassMixin):
    """Host/address resolution result wrapper.

    Parameters
    ----------
    hostname : str
        Queried hostname.
    resolution : HostResolutionResult
        Address resolution result.
    """

    hostname: str
    resolution: HostResolutionResult


@dc.dataclass(slots=True, frozen=True)
class CanonicalNameResult(DataclassMixin):
    """Canonical name resolution wrapper.

    Parameters
    ----------
    hostname : str
        Queried hostname.
    canonical_name : str
        Canonical DNS name.
    """

    hostname: str
    canonical_name: str


DNSIntegrationDispatchResult = DomainDNSResult | ReverseDNSResult | EmailDNSResult


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


class DNSIntegration:
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
    ) -> DNSIntegrationDispatchResult:
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
        DNSIntegrationDispatchResult
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
                request.ip_address,
                search=search,
                include_blocklists=include_blocklists,
            )

        return await self.lookup_email(
            request.email,
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
