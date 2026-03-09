from __future__ import annotations

import dataclasses as dc
from typing import Self

import httpx

from reconflux.net.http._errors import HTTPError
from reconflux.net.http._options import ClientOptions


@dc.dataclass(slots=True)
class HTTPIntegration:
    """Base class for HTTP-backed integrations.

    Owns an ``httpx.AsyncClient`` and exposes async context manager and
    explicit close semantics so integrations can be used either with
    ``async with`` or by managing the lifecycle manually.
    """

    client: httpx.AsyncClient

    async def aclose(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> Self:
        await self.client.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.client.__aexit__(*args)


def new_async_httpx_client(
    client_options: ClientOptions | None = None,
) -> httpx.AsyncClient:
    client_options = client_options or ClientOptions()
    client_kwargs = client_options.to_client_kwargs()
    return httpx.AsyncClient(**client_kwargs)


def validate_response(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        context = {
            'url': str(exc.request.url),
            'status_code': exc.response.status_code,
        }
        raise HTTPError(
            f'HTTP request failed with status {exc.response.status_code}.',
            context=context,
        ) from exc
