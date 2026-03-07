import dataclasses as dc
from typing import TYPE_CHECKING, Any, ClassVar

from reconflux.core import DataclassMixin
from reconflux.net.http import (
    HTTPClientOptions,
    httpx_retry,
    new_async_httpx_client,
    validate_response,
)

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


class CertshProvider:
    url: ClassVar[str] = 'https://crt.sh/'

    def __init__(self, client_options: HTTPClientOptions | None = None) -> None:
        self._client = new_async_httpx_client(
            client_options,
            headers={
                'Accept': 'application/json',
            },
        )

    @httpx_retry()
    async def _fetch_certsh(self, domain: str) -> list[dict]:
        response = await self._client.get(
            self.url,
            params={
                'q': f'%.{domain}',
                'output': 'json',
            },
        )
        validate_response(response)
        return response.json()

    async def get_subdomain(self, domain: str) -> SubdomainResult:
        response_json = await self._fetch_certsh(domain)
        subdomains = set()
        for hostname in walk_certsh_response(response_json, domain):
            subdomains.add(hostname)

        return SubdomainResult(
            domain=domain,
            total=len(subdomains),
            subdomains=sorted(subdomains),
        )
