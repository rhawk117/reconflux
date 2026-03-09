from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

import httpx

from reconflux.net.http._errors import HTTPError
from reconflux.net.http._options import ClientOptions

if TYPE_CHECKING:
    from reconflux.net.http import HttpPerformancePreset


class HTTPIntegration:
    """Base class for HTTP-backed integrations.

    Owns an ``httpx.AsyncClient`` and exposes async context manager and
    explicit close semantics so integrations can be used either with
    ``async with`` or by managing the lifecycle manually.
    """

    def __init__(
        self,
        performance: HttpPerformancePreset = 'default',
        options: ClientOptions | None = None,
    ) -> None:
        options = options or ClientOptions()
        options = options.performance_preset(performance)
        self.client = new_async_httpx_client(options)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> Self:
        await self.client.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
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
