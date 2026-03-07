from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from reconflux.net.http._errors import HTTPError
from reconflux.net.http._options import EventHooks, HTTPClientOptions

if TYPE_CHECKING:
    from collections.abc import Mapping


def new_async_httpx_client(
    settings: HTTPClientOptions | None = None,
    *,
    event_hooks: EventHooks | None = None,
    headers: Mapping[str, str] | None = None,
    cookies: httpx.Cookies | None = None,
    proxy: httpx.Proxy | str | httpx.URL | None = None,
    auth: httpx.Auth | None = None,
    mounts: Mapping[str, httpx.AsyncBaseTransport | None] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    params: httpx.QueryParams | Mapping[str, str] | None = None,
) -> httpx.AsyncClient:
    resolved_settings = settings or HTTPClientOptions()
    kwargs = resolved_settings.to_async_client_kwargs(
        event_hooks=event_hooks,
        headers=headers,
        cookies=cookies,
        proxy=proxy,
        auth=auth,
        mounts=mounts,
        transport=transport,
        params=params,
    )

    return httpx.AsyncClient(**kwargs)


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
