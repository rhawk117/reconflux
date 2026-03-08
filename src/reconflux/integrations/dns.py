from __future__ import annotations

import dataclasses as dc

from email_validator import EmailNotValidError as EmailNotValidError
from email_validator import validate_email

from reconflux.concurrency import (
    ConcurrencyIntegrationMixin,
    DispatchableTask,
    collect_concurrently,
)
from reconflux.core import DataclassMixin
from reconflux.net.dns import (
    DNSClient,
    DNSClientOptions,
    DNSRecordType,
    DNSResolutionError,
    ReverseLookupResult,
)


def get_default_blocklist() -> set[str]:
    return {
        'zen.spamhaus.org',
        'bl.spamcop.net',
        'dnsbl.sorbs.net',
        'b.barracudacentral.org',
    }


@dc.dataclass(slots=True)
class DnsblMatch(DataclassMixin):
    blocklist: str
    answer: str


@dc.dataclass(slots=True)
class DnsblResult(DataclassMixin):
    ip: str
    matches: list[DnsblMatch]

    @property
    def is_listed(self) -> bool:
        return bool(self.matches)


@dc.dataclass(slots=True)
class BlocklistTask(DispatchableTask[list[DnsblMatch]]):
    reverse_ip: str
    blocklist: str
    client: DNSClient

    def get_task_name(self) -> str:
        return self.blocklist

    async def __call__(self) -> list[DnsblMatch]:
        try:
            result = await self.client.resolve_a(f'{self.reverse_ip}.{self.blocklist}')
        except DNSResolutionError:
            return []

        return [
            DnsblMatch(blocklist=self.blocklist, answer=record.value)
            for record in result.records
        ]


@dc.dataclass(slots=True)
class DnsResolveTask(DispatchableTask[list[str]]):
    client: DNSClient
    domain: str
    record_type: DNSRecordType

    def get_task_name(self) -> str:
        return f'reconflux.dns_resolve:{self.domain}_{self.record_type}'

    async def __call__(self) -> list[str]:
        try:
            result = await self.client.resolve(self.domain, record_type=self.record_type)
            return [r.value for r in result.records]
        except DNSResolutionError:
            return []


@dc.dataclass(slots=True)
class ReverseNameTask(DispatchableTask[ReverseLookupResult]):
    ip: str
    client: DNSClient

    def get_task_name(self) -> str:
        return self.ip

    async def __call__(self) -> ReverseLookupResult:
        return await self.client.resolve_address(self.ip)


@dc.dataclass(slots=True)
class DomainRecord(DataclassMixin):
    """All DNS record types for a domain, keyed by record type."""

    domain: str
    a: list[str]
    aaaa: list[str]
    cname: list[str]
    mx: list[str]
    ns: list[str]
    ptr: list[str]
    soa: list[str]
    srv: list[str]
    txt: list[str]
    caa: list[str]


@dc.dataclass(slots=True)
class ReverseSearchResult(DataclassMixin):
    """PTR lookup results for one or more IP addresses."""

    lookups: dict[str, ReverseLookupResult]
    failures: dict[str, str]

    @property
    def succeeded(self) -> bool:
        return not self.failures


@dc.dataclass(slots=True)
class EmailRecord(DataclassMixin):
    email: str
    domain: str
    mx_records: list[str]
    spf: str | None
    dmarc: str | None


class DNSIntegration(ConcurrencyIntegrationMixin):
    """
    DNS integration backed by a shared ``DNSClient``.

    Parameters
    ----------
    client_options : DNSClientOptions, optional
        DNS client configuration. Defaults to ``DNSClientOptions()``.
    """

    def __init__(
        self,
        client_options: DNSClientOptions | None = None,
        blocklist_extras: set[str] | None = None,
    ) -> None:
        self._client = DNSClient(options=client_options or DNSClientOptions())
        self.blocklist = get_default_blocklist()
        if blocklist_extras:
            self.blocklist.update(blocklist_extras)

    @property
    def client(self) -> DNSClient:
        return self._client

    async def search(self, domain: str) -> DomainRecord:
        """
        Enumerate all DNS record types for a domain concurrently.

        Parameters
        ----------
        domain : str
            The domain name to enumerate.

        Returns
        -------
        DomainRecord
        """
        results = await self.dispatch(
            DnsResolveTask(domain=domain, client=self.client, record_type=record_type)
            for record_type in DNSRecordType
        )

        def get(rt: DNSRecordType) -> list[str]:
            return results.values.get(f'reconflux.dns_resolve:{domain}_{rt}', [])

        return DomainRecord(
            domain=domain,
            a=get(DNSRecordType.A),
            aaaa=get(DNSRecordType.AAAA),
            cname=get(DNSRecordType.CNAME),
            mx=get(DNSRecordType.MX),
            ns=get(DNSRecordType.NS),
            ptr=get(DNSRecordType.PTR),
            soa=get(DNSRecordType.SOA),
            srv=get(DNSRecordType.SRV),
            txt=get(DNSRecordType.TXT),
            caa=get(DNSRecordType.CAA),
        )

    async def reverse_search(self, *ips: str) -> ReverseSearchResult:
        """
        Reverse DNS lookup for one or more IP addresses (PTR records).

        Parameters
        ----------
        *ips : str
            IPv4 or IPv6 addresses to look up.

        Returns
        -------
        ReverseSearchResult
        """
        results = await self.dispatch(ReverseNameTask(ip, self._client) for ip in ips)
        return ReverseSearchResult(lookups=results.values, failures=results.failures)

    async def search_email(self, email: str) -> EmailRecord:
        """
        Email domain DNS analysis: MX, SPF, and DMARC.

        Parameters
        ----------
        email : str
            The email address to analyse.

        Returns
        -------
        EmailRecord

        Raises
        ------
        EmailNotValidError
            If the email address fails validation.
        """
        validated = validate_email(email, check_deliverability=False)
        domain = validated.domain
        client = self._client

        results = await collect_concurrently({
            'mx': DnsResolveTask(client, domain, DNSRecordType.MX),
            'txt': DnsResolveTask(client, domain, DNSRecordType.TXT),
            'dmarc_txt': DnsResolveTask(client, f'_dmarc.{domain}', DNSRecordType.TXT),
        })
        out = results.values
        spf = next((r for r in out['txt'] if r.lower().startswith('v=spf1')), None)
        dmarc = next(
            (r for r in out['dmarc_txt'] if r.lower().startswith('v=dmarc1')), None
        )

        return EmailRecord(
            email=validated.normalized,
            domain=domain,
            mx_records=out['mx'],
            spf=spf,
            dmarc=dmarc,
        )

    async def check_blocklist(self, ip_address: str) -> DnsblResult:
        reversed_ip = '.'.join(ip_address.split('.')[::-1])

        results = await self.dispatch(
            BlocklistTask(reversed_ip, bl, self.client) for bl in self.blocklist
        )
        matches = [
            match for match_list in results.values.values() for match in match_list
        ]
        return DnsblResult(ip=ip_address, matches=matches)
