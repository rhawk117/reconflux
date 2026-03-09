from __future__ import annotations

import ipaddress
from collections.abc import Generator
from typing import Any, ClassVar, NamedTuple

import httpx

from reconflux.net import http
from reconflux.net.rdap._errors import RDAPBootstrapError, RDAPMalformedResponseError


def _validate_services_payload(
    payload: dict[str, Any],
    *,
    bootstrap_url: str,
) -> list[Any]:
    services = payload.get('services')
    if not isinstance(services, list):
        raise RDAPMalformedResponseError(
            f'Invalid IANA bootstrap payload from {bootstrap_url!r}',
        )
    return services


def _get_first_service_url(
    service_urls: Any,
) -> str | None:
    if not isinstance(service_urls, list) or not service_urls:
        return None

    first_url = service_urls[0]
    if not isinstance(first_url, str) or not first_url.strip():
        return None

    return first_url


def _iter_service_pairs(
    services: list[Any],
) -> Generator[tuple[list[Any], str], Any]:
    for service_entry in services:
        if not isinstance(service_entry, list) or len(service_entry) != 2:
            continue

        service_targets, service_urls = service_entry
        if not isinstance(service_targets, list):
            continue

        first_url = _get_first_service_url(service_urls)
        if first_url is None:
            continue

        yield service_targets, first_url


def _get_bootstrap_service_url_for_domain(
    bootstrap_payload: dict[str, Any],
    *,
    bootstrap_url: str,
    domain_name: str,
) -> str:
    services = _validate_services_payload(
        bootstrap_payload,
        bootstrap_url=bootstrap_url,
    )
    domain_suffix = domain_name.rsplit('.', maxsplit=1)[-1].casefold()

    for service_targets, service_url in _iter_service_pairs(services):
        for service_target in service_targets:
            if domain_suffix == str(service_target).casefold():
                return service_url

    raise RDAPBootstrapError(
        f'No RDAP bootstrap service found for domain {domain_name!r}',
    )


def _get_bootstrap_service_url_for_ip(
    bootstrap_payload: dict[str, Any],
    *,
    bootstrap_url: str,
    address: str,
) -> str:
    services = _validate_services_payload(
        bootstrap_payload,
        bootstrap_url=bootstrap_url,
    )
    address_object = ipaddress.ip_address(address)

    for cidr_ranges, service_url in _iter_service_pairs(services):
        for cidr_range in cidr_ranges:
            try:
                network = ipaddress.ip_network(str(cidr_range), strict=False)
            except ValueError:
                continue

            if address_object in network:
                return service_url

    raise RDAPBootstrapError(
        f'No RDAP bootstrap service found for address {address!r}',
    )


def _get_bootstrap_service_url_for_asn(
    bootstrap_payload: dict[str, Any],
    *,
    bootstrap_url: str,
    asn: int,
) -> str:
    services = _validate_services_payload(
        bootstrap_payload,
        bootstrap_url=bootstrap_url,
    )

    for asn_ranges, service_url in _iter_service_pairs(services):
        for asn_range in asn_ranges:
            asn_text = str(asn_range)
            if '-' not in asn_text:
                continue

            try:
                start_text, end_text = asn_text.split('-', maxsplit=1)
                start_asn = int(start_text)
                end_asn = int(end_text)
            except ValueError:
                continue

            if start_asn <= asn <= end_asn:
                return service_url

    raise RDAPBootstrapError(
        f'No RDAP bootstrap service found for AS{asn}',
    )


class IANAResources(NamedTuple):
    dns_url: str
    ipv4_url: str
    ipv6_url: str
    asn_url: str


class RDAPBootstrap:
    resources: ClassVar[IANAResources] = IANAResources(
        dns_url='https://data.iana.org/rdap/dns.json',
        ipv4_url='https://data.iana.org/rdap/ipv4.json',
        ipv6_url='https://data.iana.org/rdap/ipv6.json',
        asn_url='https://data.iana.org/rdap/asn.json',
    )

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    @http.httpx_retry()
    async def _fetch_json(self, url: str) -> dict[str, Any]:
        response = await self.client.get(url)
        http.validate_response(response)
        return response.json()

    async def resolve_domain_url(self, domain_name: str) -> str:
        payload = await self._fetch_json(self.resources.dns_url)
        return _get_bootstrap_service_url_for_domain(
            payload,
            bootstrap_url=self.resources.dns_url,
            domain_name=domain_name,
        )

    async def resolve_ip_url(self, ip_address: str) -> str:
        ipaddr = ipaddress.ip_address(ip_address)
        iana_url = (
            self.resources.ipv4_url
            if isinstance(ipaddr, ipaddress.IPv4Address)
            else self.resources.ipv6_url
        )
        payload = await self._fetch_json(iana_url)
        return _get_bootstrap_service_url_for_ip(
            payload,
            bootstrap_url=iana_url,
            address=ip_address,
        )

    async def resolve_asn_url(self, asn: int) -> str:
        payload = await self._fetch_json(self.resources.asn_url)
        return _get_bootstrap_service_url_for_asn(
            payload,
            bootstrap_url=self.resources.asn_url,
            asn=asn,
        )

