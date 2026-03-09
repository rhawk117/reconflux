import dataclasses as dc
from ssl import SSLContext
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self, TypedDict

import httpx
from annotated_types import Ge
from pydantic import PositiveFloat, PositiveInt

from reconflux.core import DataclassMixin, ReconfluxModel, emit_internal_warning

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

DEFAULT_ACCEPT_HEADER = (
    'text/html,application/xhtml+xml,application/xml;q=0.9,'
    'image/avif,image/webp,image/apng,*/*;q=0.8'
)
DEFAULT_ACCEPT_ENCODING_HEADER = 'gzip, deflate, br'
DEFAULT_ACCEPT_LANGUAGE_HEADER = 'en-US,en;q=0.9'
DEFAULT_CACHE_CONTROL_HEADER = 'no-cache'
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'
)


def common_http_headers(
    *,
    user_agent: str | None = None,
    accept: str | None = None,
    accept_encoding: str | None = None,
    accept_language: str | None = None,
    cache_control: str | None = None,
    pragma: str | None = None,
    upgrade_insecure_requests: str | None = '1',
    extra_headers: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """
    Build a dictionary of common browser-like HTTP headers.

    This helper provides a lightweight set of broadly useful request headers
    suitable for navigation-oriented HTTP requests. Explicit arguments override
    the built-in defaults. Additional headers may be supplied through
    ``extra_headers`` and will take final precedence.

    Parameters
    ----------
    user_agent : str | None, optional
        Value to use for the ``User-Agent`` header. When ``None``, a default
        Reconflux user agent is used.
    accept : str | None, optional
        Value to use for the ``Accept`` header. When ``None``, a broad
        browser-like default is used.
    accept_encoding : str | None, optional
        Value to use for the ``Accept-Encoding`` header. When ``None``,
        ``'gzip, deflate, br'`` is used.
    accept_language : str | None, optional
        Value to use for the ``Accept-Language`` header. When ``None``,
        ``'en-US,en;q=0.9'`` is used.
    cache_control : str | None, optional
        Value to use for the ``Cache-Control`` header. When ``None``,
        ``'no-cache'`` is used.
    pragma : str | None, optional
        Optional value for the ``Pragma`` header. When ``None``, the header is
        omitted.
    upgrade_insecure_requests : str | None, optional
        Optional value for the ``Upgrade-Insecure-Requests`` header. When
        ``None``, the header is omitted. Defaults to ``'1'``.
    extra_headers : Mapping[str, str] | None, optional
        Additional headers to merge into the output. These headers override any
        previously defined values.

    Returns
    -------
    dict[str, str]
        A dictionary containing the resolved HTTP headers.

    Examples
    --------
    >>> common_http_headers()
    {'Accept': 'text/html,...', 'Accept-Encoding': 'gzip, deflate, br', ...}

    >>> common_http_headers(user_agent='Mozilla/5.0', extra_headers={'X-Test': 'true'})
    {'Accept': 'text/html,...', 'User-Agent': 'Mozilla/5.0', 'X-Test': 'true'}
    """
    headers: dict[str, str] = {
        'Accept': DEFAULT_ACCEPT_HEADER if accept is None else accept,
        'Accept-Encoding': (
            DEFAULT_ACCEPT_ENCODING_HEADER if accept_encoding is None else accept_encoding
        ),
        'Accept-Language': (
            DEFAULT_ACCEPT_LANGUAGE_HEADER if accept_language is None else accept_language
        ),
        'Cache-Control': (
            DEFAULT_CACHE_CONTROL_HEADER if cache_control is None else cache_control
        ),
        'User-Agent': DEFAULT_USER_AGENT if user_agent is None else user_agent,
    }

    if pragma is not None:
        headers['Pragma'] = pragma

    if upgrade_insecure_requests is not None:
        headers['Upgrade-Insecure-Requests'] = upgrade_insecure_requests

    if extra_headers:
        headers.update(extra_headers)

    return headers


class EventHooks(TypedDict, total=False):
    """Typed mapping of supported asynchronous HTTP event hooks."""

    request: list[Callable[[httpx.Request], Awaitable[None]]]
    response: list[Callable[[httpx.Response], Awaitable[None]]]


class HttpPerformanceOptions(ReconfluxModel):
    """
    Performance-oriented configuration for an ``httpx`` client.

    This model encapsulates timeout, connection pool, redirect, and protocol
    settings that influence client responsiveness and concurrency behavior.
    Preset constructors are provided for common usage profiles.

    Attributes
    ----------
    timeout : PositiveFloat
        Default overall timeout applied to request operations.
    connect_timeout : PositiveFloat
        Maximum time allowed to establish a connection.
    read_timeout : PositiveFloat
        Maximum time allowed while reading response data.
    write_timeout : PositiveFloat
        Maximum time allowed while sending request data.
    pool_timeout : PositiveFloat
        Maximum time to wait for an available pooled connection.
    max_connections : PositiveInt
        Maximum total number of concurrent connections.
    max_keepalive_connections : int | None
        Maximum number of idle keep-alive connections to retain.
    keepalive_expiry : PositiveFloat | None
        Number of seconds an idle keep-alive connection may remain open.
    http2 : bool
        Whether HTTP/2 support is enabled.
    http1 : bool
        Whether HTTP/1.1 support is enabled.
    follow_redirects : bool
        Whether redirects are automatically followed.
    max_redirects : PositiveInt
        Maximum number of redirects to follow.

    Notes
    -----
    These options are converted into ``httpx.Timeout`` and ``httpx.Limits``
    instances when preparing client keyword arguments.
    """

    timeout: PositiveFloat = 10.0
    connect_timeout: PositiveFloat = 5.0
    read_timeout: PositiveFloat = 10.0
    write_timeout: PositiveFloat = 10.0
    pool_timeout: PositiveFloat = 5.0

    max_connections: PositiveInt = 100
    max_keepalive_connections: Annotated[int | None, Ge(0)] = 20
    keepalive_expiry: PositiveFloat | None = 10.0
    http2: bool = False
    http1: bool = True
    follow_redirects: bool = True
    max_redirects: PositiveInt = 20

    def get_timeout(self) -> httpx.Timeout:
        """
        Build an ``httpx.Timeout`` instance from the configured timeout values.

        Returns
        -------
        httpx.Timeout
            Timeout object containing the configured overall, connect, read,
            write, and pool timeout values.
        """
        return httpx.Timeout(
            timeout=self.timeout,
            connect=self.connect_timeout,
            read=self.read_timeout,
            write=self.write_timeout,
            pool=self.pool_timeout,
        )

    def get_limits(self) -> httpx.Limits:
        """
        Build an ``httpx.Limits`` instance from the configured pool settings.

        Returns
        -------
        httpx.Limits
            Limits object containing the configured connection and keep-alive
            pool constraints.
        """
        return httpx.Limits(
            max_connections=self.max_connections,
            max_keepalive_connections=self.max_keepalive_connections,
            keepalive_expiry=self.keepalive_expiry,
        )

    @classmethod
    def balanced(cls) -> Self:
        """
        Create a balanced client performance profile.

        Returns
        -------
        Self
            A default configuration intended to provide a reasonable trade-off
            between responsiveness and throughput.
        """
        return cls()

    @classmethod
    def high_throughput(cls) -> Self:
        """
        Create a high-throughput client performance profile.

        This preset favors larger connection pools and longer-lived connections
        for workloads that issue many concurrent requests.

        Returns
        -------
        Self
            A performance configuration tuned for higher concurrency.
        """
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
        )

    @classmethod
    def low_latency(cls) -> Self:
        """
        Create a low-latency client performance profile.

        This preset favors shorter timeouts and reduced redirect behavior for
        fast-failing, responsive workloads.

        Returns
        -------
        Self
            A performance configuration tuned for lower latency.
        """
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
        )

    @classmethod
    def scraping(cls) -> Self:
        """
        Create a scraping-oriented client performance profile.

        This preset uses more tolerant timeouts and moderate concurrency to
        support workloads that fetch many remote pages.

        Returns
        -------
        Self
            A performance configuration tuned for scraping-style traffic.
        """
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
        )

    @classmethod
    def constrained(cls) -> Self:
        """
        Create a resource-constrained client performance profile.

        This preset reduces concurrency and keep-alive usage for environments
        where connection count or memory usage should remain modest.

        Returns
        -------
        Self
            A performance configuration tuned for constrained environments.
        """
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
        )

    def to_client_kwargs(self) -> dict[str, Any]:
        """
        Serialize the performance options into ``httpx.AsyncClient`` kwargs.

        Returns
        -------
        dict[str, Any]
            Keyword arguments representing timeout, pooling, redirect, and
            protocol configuration for an ``httpx`` client.
        """
        return {
            'timeout': self.get_timeout(),
            'limits': self.get_limits(),
            'follow_redirects': self.follow_redirects,
            'max_redirects': self.max_redirects,
            'http2': self.http2,
            'http1': self.http1,
        }


HttpPerformancePreset = Literal[
    'default',
    'high_throughput',
    'low_latency',
    'scraping',
    'constrained',
]


def get_performance_preset(preset: str) -> HttpPerformanceOptions:
    """
    Resolve a named HTTP client performance preset.

    Parameters
    ----------
    preset : str
        Name of the preset to resolve.

    Returns
    -------
    HttpPerformanceOptions
        The resolved performance options. If the preset is not recognized, a
        default ``HttpPerformanceOptions`` instance is returned and an internal
        warning is emitted.

    Warns
    -----
    Internal warning
        Emitted when an unrecognized preset name is provided.
    """
    preset_map: dict[str, Callable[[], HttpPerformanceOptions]] = {
        'default': HttpPerformanceOptions,
        'high_throughput': HttpPerformanceOptions.high_throughput,
        'low_latency': HttpPerformanceOptions.low_latency,
        'scraping': HttpPerformanceOptions.scraping,
        'constrained': HttpPerformanceOptions.constrained,
    }

    performance_factory = preset_map.get(preset)
    if performance_factory is None:
        emit_internal_warning(
            f'Unrecognized http performance preset `{preset}` '
            'the default preset will be used instead'
        )
        return HttpPerformanceOptions()

    return performance_factory()


@dc.dataclass(slots=True)
class ClientOptions(DataclassMixin):
    """
    Immutable-style builder for ``httpx.AsyncClient`` initialization arguments.

    This dataclass combines transport-adjacent client configuration such as
    base URL, proxy settings, headers, event hooks, and protocol verification
    with a separate ``HttpPerformanceOptions`` object.

    Attributes
    ----------
    performance : HttpPerformanceOptions
        Performance configuration used to derive timeout and pooling settings.
    base_url : httpx.URL | str | None
        Optional base URL applied to relative requests.
    verify : bool | str | SSLContext
        TLS certificate verification behavior.
    trust_env : bool
        Whether environment-based proxy and certificate settings are used.
    event_hooks : EventHooks | None
        Optional asynchronous request and response event hooks.
    headers : Mapping[str, str] | None
        Optional default headers for all requests.
    cookies : httpx.Cookies | None
        Optional client-level cookie state.
    proxy : httpx.Proxy | str | httpx.URL | None
        Optional proxy configuration.
    auth : httpx.Auth | None
        Optional authentication implementation.
    mounts : Mapping[str, httpx.AsyncBaseTransport | None] | None
        Optional per-prefix transport mounts.
    transport : httpx.AsyncBaseTransport | None
        Optional custom transport.
    params : httpx.QueryParams | Mapping[str, str] | None
        Optional default query parameters.
    user_agent : str
        Default user agent used when common headers are enabled without an
        explicit user agent override.
    default_encoding : str | Callable[[bytes], str]
        Default response encoding or dynamic encoding resolver.
    """

    performance: HttpPerformanceOptions = dc.field(default_factory=HttpPerformanceOptions)
    base_url: httpx.URL | str | None = None
    verify: bool | str | SSLContext = True
    trust_env: bool = False
    event_hooks: EventHooks | None = None
    headers: Mapping[str, str] | None = None
    cookies: httpx.Cookies | None = None
    proxy: httpx.Proxy | str | httpx.URL | None = None
    auth: httpx.Auth | None = None
    mounts: Mapping[str, httpx.AsyncBaseTransport | None] | None = None
    transport: httpx.AsyncBaseTransport | None = None
    params: httpx.QueryParams | Mapping[str, str] | None = None
    user_agent: str = DEFAULT_USER_AGENT
    default_encoding: str | Callable[[bytes], str] = 'utf-8'

    def performance_preset(self, preset: HttpPerformancePreset) -> Self:
        """
        Return a copy with a named performance preset applied.

        Parameters
        ----------
        preset : HttpPerformancePreset
            Name of the performance preset to apply.

        Returns
        -------
        Self
            A new instance with the resolved performance configuration.
        """
        performance_options = get_performance_preset(preset)
        return self.replace(performance=performance_options)

    def use_common_headers(
        self,
        *,
        user_agent: str | None = None,
        accept: str | None = None,
        accept_encoding: str | None = None,
        accept_language: str | None = None,
        cache_control: str | None = None,
        pragma: str | None = None,
        upgrade_insecure_requests: str | None = '1',
        extra_headers: Mapping[str, str] | None = None,
    ) -> Self:
        """
        Return a copy with common browser-like headers merged into the client.

        Existing headers are preserved unless overwritten by generated or
        explicitly provided values.

        Parameters
        ----------
        user_agent : str | None, optional
            Value to use for the ``User-Agent`` header. When ``None``, the
            instance-level ``user_agent`` value is used.
        accept : str | None, optional
            Value to use for the ``Accept`` header.
        accept_encoding : str | None, optional
            Value to use for the ``Accept-Encoding`` header.
        accept_language : str | None, optional
            Value to use for the ``Accept-Language`` header.
        cache_control : str | None, optional
            Value to use for the ``Cache-Control`` header.
        pragma : str | None, optional
            Optional value for the ``Pragma`` header.
        upgrade_insecure_requests : str | None, optional
            Optional value for the ``Upgrade-Insecure-Requests`` header.
        extra_headers : Mapping[str, str] | None, optional
            Additional headers to merge after the generated common headers.

        Returns
        -------
        Self
            A new instance with merged headers.
        """
        merged_headers = dict(self.headers or {})
        merged_headers.update(
            common_http_headers(
                user_agent=self.user_agent if user_agent is None else user_agent,
                accept=accept,
                accept_encoding=accept_encoding,
                accept_language=accept_language,
                cache_control=cache_control,
                pragma=pragma,
                upgrade_insecure_requests=upgrade_insecure_requests,
                extra_headers=extra_headers,
            )
        )
        return self.replace(headers=merged_headers)

    def to_client_kwargs(self) -> dict[str, Any]:
        """
        Serialize the client initialization state into ``httpx.AsyncClient`` kwargs.

        Returns
        -------
        dict[str, Any]
            Keyword arguments suitable for constructing an ``httpx.AsyncClient``.
        """
        return {
            **self.performance.to_client_kwargs(),
            'base_url': self.base_url or '',
            'verify': self.verify,
            'trust_env': self.trust_env,
            'headers': self.headers,
            'cookies': self.cookies,
            'proxy': self.proxy,
            'auth': self.auth,
            'mounts': self.mounts,
            'transport': self.transport,
            'event_hooks': self.event_hooks,
            'params': self.params,
            'default_encoding': self.default_encoding,
        }

    def update_mappings(
        self,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Self:
        newheaders = dict(self.headers or {})
        newparams = dict(self.params or {})

        if headers:
            newheaders.update(headers)
        if params:
            newparams.update(newparams)

        return self.replace(
            headers=newheaders,
            params=newparams,
        )
