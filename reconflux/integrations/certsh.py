import dataclasses as dc
from typing import TYPE_CHECKING, Any

import httpx

from reconflux.core import DataclassMixin
from reconflux.net import http

if TYPE_CHECKING:
    from collections.abc import Generator


@dc.dataclass(slots=True)
class SubdomainResult(DataclassMixin):
    domain: str
    total: int
    subdomains: list[str]


def normalize_hostname(hostname: str) -> str:
    return hostname.strip().lower().rstrip('.')


def iter_name_values(name_value: str, domain: str) -> Generator[str, Any]:
    for line in str(name_value).splitlines():
        hostname = normalize_hostname(line)
        if hostname and hostname != domain:
            yield hostname


def walk_certsh_response(response_json: list[dict], domain: str) -> Generator[str, Any]:
    """
    Walk the JSON response from cert.sh and yield subdomains
    by looking at the `name_value` and `common_name` fields
    to extract hostnames.

    Yields
    ------
    str
    """
    for entry in response_json:
        if name_value := entry.get('name_value'):
            yield from iter_name_values(name_value, domain)
        elif common_name := entry.get('common_name'):
            hostname = normalize_hostname(common_name)
            if hostname and hostname != domain:
                yield hostname


def certsh_clientmaker(
    base_url: str = 'https://crt.sh',
    performance: http.HttpPerformancePreset = 'default',
) -> httpx.AsyncClient:
    options = (
        http
        .ClientOptions(base_url=base_url)
        .performance_preset(performance)
        .use_common_headers(
            accept='application/json',
        )
    )
    return http.new_async_httpx_client(options)


@dc.dataclass(slots=True)
class CertshIntegration:
    client: httpx.AsyncClient = dc.field(default_factory=certsh_clientmaker)

    @http.httpx_retry(attempts=3)
    async def fetch(self, domain: str) -> list[dict]:
        response = await self.client.get(
            '/',
            params={
                'output': 'json',
                'q': f'%.{domain}',
            },
        )
        http.validate_response(response)
        return response.json()

    async def get_subdomains(self, domain: str) -> SubdomainResult:
        response_json = await self.fetch(domain)
        subdomains = set()
        for hostname in walk_certsh_response(response_json, domain):
            subdomains.add(hostname)

        return SubdomainResult(
            domain=domain,
            total=len(subdomains),
            subdomains=sorted(subdomains),
        )
