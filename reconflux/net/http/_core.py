from __future__ import annotations

import httpx

from reconflux.net.http._errors import HTTPError
from reconflux.net.http._options import ClientOptions


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
