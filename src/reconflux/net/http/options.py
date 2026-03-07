
from collections.abc import Awaitable, Callable, Mapping
from ssl import SSLContext  # noqa: TC003
from typing import Annotated, Any, Literal, TypedDict

import httpx
from annotated_types import Ge
from pydantic import PositiveFloat, PositiveInt  # noqa: TC002

from reconflux.core import ReconfluxModel

type HTTPEventName = Literal['request', 'response']
type HTTPEventHook = (
    Callable[[httpx.Request], Awaitable[None]]
    | Callable[[httpx.Response], Awaitable[None]]
)


class EventHooks(TypedDict, total=False):
    request: list[Callable[[httpx.Request], Awaitable[None]]]
    response: list[Callable[[httpx.Response], Awaitable[None]]]


class HTTPClientOptions(ReconfluxModel):
    base_url: httpx.URL | str | None = None

    timeout: PositiveFloat = 10.0
    connect_timeout: PositiveFloat = 5.0
    read_timeout: PositiveFloat = 10.0
    write_timeout: PositiveFloat = 10.0
    pool_timeout: PositiveFloat = 5.0

    max_connections: PositiveInt = 100
    max_keepalive_connections: Annotated[int | None, Ge(0)] = 20
    keepalive_expiry: PositiveFloat | None = 10.0

    follow_redirects: bool = True
    http2: bool = True
    verify: bool | str | SSLContext = True
    max_redirects: PositiveInt = 20
    trust_env: bool = False

    user_agent: str = 'reconflux/0.1'
    default_encoding: str | Callable[[bytes], str] = 'utf-8'

    def get_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            timeout=self.timeout,
            connect=self.connect_timeout,
            read=self.read_timeout,
            write=self.write_timeout,
            pool=self.pool_timeout,
        )

    def get_limits(self) -> httpx.Limits:
        return httpx.Limits(
            max_connections=self.max_connections,
            max_keepalive_connections=self.max_keepalive_connections,
            keepalive_expiry=self.keepalive_expiry,
        )

    def get_default_headers(
        self,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        merged_headers = {'User-Agent': self.user_agent}

        if headers:
            merged_headers.update(headers)

        return merged_headers

    def to_async_client_kwargs(
        self,
        *,
        event_hooks: EventHooks | None = None,
        headers: Mapping[str, str] | None = None,
        cookies: httpx.Cookies | None = None,
        proxy: httpx.Proxy | str | httpx.URL | None = None,
        auth: httpx.Auth | None = None,
        mounts: Mapping[str, httpx.AsyncBaseTransport | None] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        params: httpx.QueryParams | Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            'base_url': self.base_url or '',
            'timeout': self.get_timeout(),
            'limits': self.get_limits(),
            'follow_redirects': self.follow_redirects,
            'http2': self.http2,
            'verify': self.verify,
            'max_redirects': self.max_redirects,
            'trust_env': self.trust_env,
            'headers': self.get_default_headers(headers),
            'cookies': cookies,
            'proxy': proxy,
            'auth': auth,
            'mounts': mounts,
            'transport': transport,
            'event_hooks': event_hooks,
            'params': params,
            'default_encoding': self.default_encoding,
        }

    @classmethod
    def balanced(cls) -> HTTPClientOptions:
        return cls()

    @classmethod
    def high_throughput(cls) -> HTTPClientOptions:
        return cls(
            timeout=15.0,
            connect_timeout=5.0,
            read_timeout=15.0,
            write_timeout=15.0,
            pool_timeout=5.0,
            max_connections=250,
            max_keepalive_connections=100,
            keepalive_expiry=20.0,
            follow_redirects=True,
            http2=True,
            trust_env=False,
        )

    @classmethod
    def low_latency(cls) -> HTTPClientOptions:
        return cls(
            timeout=5.0,
            connect_timeout=2.0,
            read_timeout=4.0,
            write_timeout=4.0,
            pool_timeout=1.0,
            max_connections=100,
            max_keepalive_connections=50,
            keepalive_expiry=5.0,
            follow_redirects=False,
            http2=True,
            trust_env=False,
        )

    @classmethod
    def scraping(cls) -> HTTPClientOptions:
        return cls(
            timeout=20.0,
            connect_timeout=5.0,
            read_timeout=20.0,
            write_timeout=10.0,
            pool_timeout=5.0,
            max_connections=150,
            max_keepalive_connections=50,
            keepalive_expiry=15.0,
            follow_redirects=True,
            http2=True,
            trust_env=False,
        )

    @classmethod
    def constrained(cls) -> HTTPClientOptions:
        return cls(
            timeout=10.0,
            connect_timeout=5.0,
            read_timeout=10.0,
            write_timeout=10.0,
            pool_timeout=5.0,
            max_connections=25,
            max_keepalive_connections=10,
            keepalive_expiry=5.0,
            follow_redirects=True,
            http2=True,
            trust_env=False,
        )

    def with_overrides(self, **updates: object) -> HTTPClientOptions:
        return self.model_copy(update=updates)
