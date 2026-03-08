"""
**reconflux.integrations.dns**
-----------------

DNS integration providing domain enumeration, reverse lookup, email DNS
analysis, and DNSBL blocklist checking.

``DNSIntegration`` is the top-level class that owns a shared ``DNSClient``
and exposes lookup methods alongside a nested ``Blocklist`` subclass that
inherits the same resolver and client configuration.
"""

from __future__ import annotations

import asyncio
import dataclasses as dc
from typing import ClassVar

from reconflux.core import DataclassMixin
from reconflux.net.dns import (
    DNSClient,
    DNSClientOptions,
    DNSRecordType,
    DNSResolutionError,
    ReverseLookupResult,
)

# ── Result types ──────────────────────────────────────────────────────────────

@dc.dataclass(slots=True)
class DnsblMatch(DataclassMixin):
    """A single DNSBL hit — the blocklist that listed the IP and the A record answer."""

    blocklist: str
    answer: str


@dc.dataclass(slots=True)
class DnsblResult(DataclassMixin):
    """Result of a DNSBL check for an IP address."""

    ip: str
    matches: list[DnsblMatch]

    @property
    def is_listed(self) -> bool:
        """``True`` if the IP is listed on at least one blocklist."""
        return bool(self.matches)


@dc.dataclass(slots=True)
class DomainRecord(DataclassMixin):
    """Comprehensive DNS record set for a domain."""

    domain: str
    a_records: list[str]
    aaaa_records: list[str]
    mx_records: list[str]
    ns_records: list[str]
    txt_records: list[str]
    caa_records: list[str]
    cname: str | None = None


@dc.dataclass(slots=True)
class EmailRecord(DataclassMixin):
    """Email domain DNS analysis: MX, SPF, and DMARC records."""

    email: str
    domain: str
    mx_records: list[str]
    spf: str | None
    dmarc: str | None


async def _safe_resolve(
    client: DNSClient,
    qname: str,
    record_type: DNSRecordType,
) -> list[str]:
    try:
        result = await client.resolve(qname, record_type=record_type)
        return [r.value for r in result.records]
    except DNSResolutionError:
        return []


async def _safe_canonical_name(client: DNSClient, hostname: str) -> str | None:
    """
    Resolve the canonical name for a hostname.

    Returns ``None`` when no CNAME chain exists or the lookup fails.
    """
    try:
        cname = await client.canonical_name(hostname)
        return cname if cname.rstrip('.') != hostname.rstrip('.') else None
    except DNSResolutionError:
        return None


class DNSIntegration:
    """
    DNS integration backed by a shared ``DNSClient``.

    Provides domain enumeration, reverse lookup, email DNS analysis, and
    DNS blocklist checking via the nested ``Blocklist`` subclass. All methods
    are ``async`` and issue DNS queries concurrently where possible.

    Parameters
    ----------
    client_options:
        DNS client configuration passed to the underlying ``DNSClient``.
        Defaults to ``DNSClientOptions()``.

    Examples
    --------
    >>> dns = DNSIntegration()
    >>> record = await dns.search("example.com")
    >>> result = await dns.blocklist.check("1.2.3.4")
    """

    def __init__(self, client_options: DNSClientOptions | None = None) -> None:
        self._client = DNSClient(options=client_options or DNSClientOptions())
        self.blocklist = self.Blocklist(self._client)

    @property
    def client(self) -> DNSClient:
        return self._client

    async def search(self, domain: str) -> DomainRecord:
        """
        Enumerate all common DNS records for a domain concurrently.

        Queries A, AAAA, MX, NS, TXT, and CAA records in parallel and
        resolves any CNAME chain.

        Parameters
        ----------
        domain:
            The domain name to enumerate.

        Returns
        -------
        DomainRecord
        """
        a, aaaa, mx, ns, txt, caa, cname = await asyncio.gather(
            _safe_resolve(self._client, domain, DNSRecordType.A),
            _safe_resolve(self._client, domain, DNSRecordType.AAAA),
            _safe_resolve(self._client, domain, DNSRecordType.MX),
            _safe_resolve(self._client, domain, DNSRecordType.NS),
            _safe_resolve(self._client, domain, DNSRecordType.TXT),
            _safe_resolve(self._client, domain, DNSRecordType.CAA),
            _safe_canonical_name(self._client, domain),
        )
        return DomainRecord(
            domain=domain,
            a_records=a,
            aaaa_records=aaaa,
            mx_records=mx,
            ns_records=ns,
            txt_records=txt,
            caa_records=caa,
            cname=cname,
        )

    async def reverse_search(self, ip: str) -> ReverseLookupResult:
        """
        Reverse DNS lookup for an IP address (PTR records).

        Parameters
        ----------
        ip:
            The IPv4 or IPv6 address to look up.

        Returns
        -------
        ReverseLookupResult

        Raises
        ------
        ReverseLookupError
            If the PTR lookup fails.
        """
        return await self._client.resolve_address(ip)

    async def search_email(self, email: str) -> EmailRecord:
        """
        Email domain DNS analysis.

        Queries MX records for mail exchangers, TXT records for SPF policy,
        and ``_dmarc.<domain>`` TXT records for DMARC policy — all in parallel.

        Parameters
        ----------
        email:
            The email address to analyse.

        Returns
        -------
        EmailRecord

        Raises
        ------
        ValueError
            If the email address has no ``@`` separator.
        """
        if '@' not in email:
            raise ValueError(f'Invalid email address: {email!r}')
        domain = email.split('@', 1)[1].lower()

        mx, txt, dmarc_txt = await asyncio.gather(
            _safe_resolve(self._client, domain, DNSRecordType.MX),
            _safe_resolve(self._client, domain, DNSRecordType.TXT),
            _safe_resolve(self._client, f'_dmarc.{domain}', DNSRecordType.TXT),
        )

        spf = next((r for r in txt if r.lower().startswith('v=spf1')), None)
        dmarc = next((r for r in dmarc_txt if r.lower().startswith('v=dmarc1')), None)

        return EmailRecord(
            email=email,
            domain=domain,
            mx_records=mx,
            spf=spf,
            dmarc=dmarc,
        )

    class Blocklist:
        """
        DNSBL blocklist checker sharing the parent ``DNSIntegration`` client.

        Checks an IPv4 address against a configurable set of DNSBL servers by
        reversing the IP octets and resolving ``<reversed-ip>.<blocklist>`` as
        an A record. All blocklist queries are issued concurrently.

        ``DNSResolutionError`` (NXDOMAIN, NoAnswer, timeouts) is silently
        treated as not listed — the expected clean response for DNSBL queries.

        Accessed via ``DNSIntegration.blocklist``.
        """

        _DEFAULT_BLOCKLISTS: ClassVar[frozenset[str]] = frozenset({
            'zen.spamhaus.org',
            'bl.spamcop.net',
            'dnsbl.sorbs.net',
            'b.barracudacentral.org',
        })

        def __init__(
            self,
            client: DNSClient,
            blocklists: set[str] | None = None,
        ) -> None:
            self._client = client
            self._blocklists: set[str] = set(blocklists or self._DEFAULT_BLOCKLISTS)

        def extend(self, extras: set[str]) -> None:
            """Add extra DNSBL hostnames to the set of checked blocklists."""
            self._blocklists.update(extras)

        async def check(self, ip: str) -> DnsblResult:
            """
            Check an IP address against all configured DNSBL servers concurrently.

            Parameters
            ----------
            ip:
                The IPv4 address to check.

            Returns
            -------
            DnsblResult
            """
            reversed_ip = '.'.join(ip.split('.')[::-1])
            blocklists = list(self._blocklists)

            results = await asyncio.gather(
                *(self._client.resolve_a(f'{reversed_ip}.{bl}') for bl in blocklists),
                return_exceptions=True,
            )

            matches: list[DnsblMatch] = []
            for blocklist, result in zip(blocklists, results, strict=False):
                if isinstance(result, Exception):
                    continue
                matches.extend(
                    DnsblMatch(blocklist=blocklist, answer=record.value)
                    for record in result.records
                )

            return DnsblResult(ip=ip, matches=matches)
