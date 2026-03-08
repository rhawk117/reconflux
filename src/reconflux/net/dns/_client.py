import socket
import time

import dns.asyncresolver
import dns.exception
import dns.name

from reconflux.net.dns._errors import DNSResolutionError, ReverseLookupError
from reconflux.net.dns._options import DNSClientOptions
from reconflux.net.dns._record_types import DNSRecordType
from reconflux.net.dns._results import (
    DNSAnswerRecord,
    DNSQueryResult,
    HostResolutionResult,
    ReverseLookupResult,
)


def new_async_dns_resolver(
    options: DNSClientOptions | None = None,
) -> dns.asyncresolver.Resolver:
    resolved_options = options or DNSClientOptions()

    resolver = dns.asyncresolver.Resolver(
        configure=resolved_options.configure_from_system
    )
    resolver.timeout = resolved_options.timeout
    resolver.lifetime = resolved_options.lifetime
    resolver.rotate = resolved_options.rotate_nameservers
    resolver.retry_servfail = resolved_options.retry_servfail
    resolver.use_edns(
        edns=0 if resolved_options.use_edns else None,
        payload=resolved_options.edns_payload,
    )

    if resolved_options.nameservers is not None:
        resolver.nameservers = list(resolved_options.nameservers)

    if resolved_options.search_domains is not None:
        resolver.search = [dns.name.from_text(d) for d in resolved_options.search_domains]

    if resolved_options.port:
        resolver.port = resolved_options.port

    return resolver


class DNSClient:
    __slots__ = (
        '_options',
        '_resolver',
    )

    def __init__(
        self,
        *,
        options: DNSClientOptions | None = None,
        resolver: dns.asyncresolver.Resolver | None = None,
    ) -> None:
        self._options = options or DNSClientOptions()
        self._resolver = resolver

    @property
    def options(self) -> DNSClientOptions:
        return self._options

    @property
    def resolver(self) -> dns.asyncresolver.Resolver:
        if self._resolver is None:
            self._resolver = new_async_dns_resolver(self._options)
        return self._resolver

    async def resolve(
        self,
        qname: str,
        *,
        record_type: DNSRecordType | str = DNSRecordType.A,
        search: bool | None = None,
        raise_on_no_answer: bool = False,
        tcp: bool = False,
    ) -> DNSQueryResult:
        started_at = time.perf_counter()

        try:
            answer = await self.resolver.resolve(
                qname,
                rdtype=str(record_type),
                search=self._resolve_search_flag(search=search),
                raise_on_no_answer=raise_on_no_answer,
                tcp=tcp,
            )
        except dns.exception.DNSException as exc:
            raise DNSResolutionError.query(record_type, qname) from exc

        response_time_ms = (time.perf_counter() - started_at) * 1000.0

        records = [
            DNSAnswerRecord(
                value=rdata.to_text(),
                ttl=getattr(answer.rrset, 'ttl', None),
                record_type=str(record_type),
            )
            for rdata in answer
        ]

        response_nameserver = None
        if answer.nameserver is not None:
            response_nameserver = str(answer.nameserver)

        return DNSQueryResult(
            query_name=qname,
            record_type=str(record_type),
            records=records,
            canonical_name=str(answer.canonical_name) if answer.canonical_name else None,
            nameserver=response_nameserver,
            port=answer.port,
            response_time_ms=response_time_ms,
        )

    async def resolve_name(
        self,
        hostname: str,
        *,
        family: int = socket.AF_UNSPEC,
        search: bool | None = None,
    ) -> HostResolutionResult:
        try:
            host_answers = await self.resolver.resolve_name(
                hostname,
                family=family,
                search=self._resolve_search_flag(search=search),
            )
        except dns.exception.DNSException as exc:
            raise DNSResolutionError.host(hostname) from exc

        ipv4_addresses: list[str] = []
        ipv6_addresses: list[str] = []

        v4 = getattr(host_answers, 'v4', None)
        if v4 is not None:
            ipv4_addresses.extend([rdata.address for rdata in v4])

        v6 = getattr(host_answers, 'v6', None)
        if v6 is not None:
            ipv6_addresses.extend([rdata.address for rdata in v6])

        return HostResolutionResult(
            hostname=hostname,
            canonical_name=str(host_answers.canonical_name()),
            ipv4_addresses=ipv4_addresses,
            ipv6_addresses=ipv6_addresses,
        )

    async def resolve_address(
        self,
        ip_address: str,
        *,
        search: bool | None = None,
    ) -> ReverseLookupResult:
        try:
            answer = await self.resolver.resolve_address(
                ip_address,
                search=self._resolve_search_flag(search=search),
            )
        except dns.exception.DNSException as exc:
            raise ReverseLookupError(
                f'Failed to perform reverse lookup for {ip_address!r}.',
                context={'ip_address': ip_address},
            ) from exc

        hostnames = [rdata.to_text().rstrip('.') for rdata in answer]

        return ReverseLookupResult(
            ip_address=ip_address,
            hostnames=hostnames,
        )

    async def canonical_name(self, hostname: str) -> str:
        try:
            canonical_name = await self.resolver.canonical_name(hostname)
        except dns.exception.DNSException as exc:
            raise DNSResolutionError.canonical(hostname) from exc

        return str(canonical_name)

    async def resolve_a(self, hostname: str) -> DNSQueryResult:
        return await self.resolve(hostname, record_type=DNSRecordType.A)

    async def resolve_aaaa(self, hostname: str) -> DNSQueryResult:
        return await self.resolve(hostname, record_type=DNSRecordType.AAAA)

    async def resolve_mx(self, hostname: str) -> DNSQueryResult:
        return await self.resolve(hostname, record_type=DNSRecordType.MX)

    async def resolve_ns(self, hostname: str) -> DNSQueryResult:
        return await self.resolve(hostname, record_type=DNSRecordType.NS)

    async def resolve_txt(self, hostname: str) -> DNSQueryResult:
        return await self.resolve(hostname, record_type=DNSRecordType.TXT)

    async def resolve_cname(self, hostname: str) -> DNSQueryResult:
        return await self.resolve(hostname, record_type=DNSRecordType.CNAME)

    def _resolve_search_flag(self, *, search: bool | None) -> bool | None:
        if search is not None:
            return search

        return self.options.use_search_by_default
