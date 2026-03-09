from __future__ import annotations

import dataclasses as dc
import ipaddress
from enum import StrEnum
from typing import TYPE_CHECKING

from reconflux.core import DataclassMixin

if TYPE_CHECKING:
    from reconflux.concurrency import TaskExecutorResult
    from reconflux.net.dns import (
        DNSQueryResult,
        HostResolutionResult,
        ReverseLookupResult,
    )


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


type DNSIntegrationResult = DomainDNSResult | ReverseDNSResult | EmailDNSResult
