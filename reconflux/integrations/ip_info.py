import dataclasses as dc
from typing import Any, Self

import httpx
from pydantic import ConfigDict

from reconflux.core import DataclassMixin, ReconfluxModel
from reconflux.net import http


class _IpInfoResponse(ReconfluxModel):
    """Base model for ipinfo.io API responses. Allows extra fields from the API."""

    model_config = ConfigDict(
        extra='ignore',
        populate_by_name=True,
        use_enum_values=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )


class IpInfoCountryFlagResponse(_IpInfoResponse):
    emoji: str
    unicode: str


class IpInfoCountryCurrencyResponse(_IpInfoResponse):
    code: str
    symbol: str


class IpInfoContinentResponse(_IpInfoResponse):
    code: str
    name: str


class IpInfoLiteResponse(_IpInfoResponse):
    """
    Response model for the ipinfo.io lite endpoint (``/lite/{ip}/json``).

    This is the free unauthenticated endpoint that returns enriched geolocation
    data including country metadata, continent, and currency info.
    """
    ip: str
    bogon: bool = False
    hostname: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    loc: str | None = None
    org: str | None = None
    postal: str | None = None
    timezone: str | None = None
    country_name: str | None = None
    country_flag: IpInfoCountryFlagResponse | None = None
    country_flag_url: str | None = None
    country_currency: IpInfoCountryCurrencyResponse | None = None
    continent: IpInfoContinentResponse | None = None
    is_eu: bool = False


class IpInfoLookupResponse(IpInfoLiteResponse):
    """
    Response model for the ipinfo.io authenticated lookup endpoint (``/{ip}``).

    Shares the same base fields as the lite response. Higher-tier plans may
    return additional fields which are captured by the ``extra='ignore'`` config.
    """


@dc.dataclass(slots=True)
class IpRecord(DataclassMixin):
    """Legacy IP record returned by ``IPInfoLegacyIntegration``."""

    ip: str
    city: str | None = None
    country: str | None = None
    postal: str | None = None
    org: str | None = None
    location: str | None = None
    timezone: str | None = None
    extras: dict = dc.field(default_factory=dict)

    @property
    def maps_link(self) -> str | None:
        if not self.location:
            return None
        return f'https://maps.google.com/?q={self.location}'


@dc.dataclass(slots=True)
class IpInfoCountryFlag(DataclassMixin):
    emoji: str
    unicode: str


@dc.dataclass(slots=True)
class IpInfoCountryCurrency(DataclassMixin):
    code: str
    symbol: str


@dc.dataclass(slots=True)
class IpInfoContinent(DataclassMixin):
    code: str
    name: str


@dc.dataclass(slots=True)
class IpLiteRecord(DataclassMixin):
    """
    IP record returned by ``IPInfoLiteIntegration`` and ``IPInfoLookupIntegration``.

    Contains enriched geolocation data including country metadata,
    continent, currency, and EU membership status.
    """
    ip: str
    hostname: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    loc: str | None = None
    org: str | None = None
    postal: str | None = None
    timezone: str | None = None
    country_name: str | None = None
    country_flag: IpInfoCountryFlag | None = None
    country_flag_url: str | None = None
    country_currency: IpInfoCountryCurrency | None = None
    continent: IpInfoContinent | None = None
    is_eu: bool = False

    @property
    def maps_link(self) -> str | None:
        if not self.loc:
            return None
        return f'https://maps.google.com/?q={self.loc}'

    @classmethod
    def parse_response(cls, response: IpInfoLiteResponse) -> Self:
        country_flag = None
        if response.country_flag:
            country_flag = IpInfoCountryFlag(
                emoji=response.country_flag.emoji,
                unicode=response.country_flag.unicode,
            )

        country_currency = None
        if response.country_currency:
            country_currency = IpInfoCountryCurrency(
                code=response.country_currency.code,
                symbol=response.country_currency.symbol,
            )

        continent = None
        if response.continent:
            continent = IpInfoContinent(
                code=response.continent.code,
                name=response.continent.name,
            )

        return cls(
            ip=response.ip,
            hostname=response.hostname,
            city=response.city,
            region=response.region,
            country=response.country,
            loc=response.loc,
            org=response.org,
            postal=response.postal,
            timezone=response.timezone,
            country_name=response.country_name,
            country_flag=country_flag,
            country_flag_url=response.country_flag_url,
            country_currency=country_currency,
            continent=continent,
            is_eu=response.is_eu,
        )


def ip_info_clientmaker(
    performance: http.HttpPerformancePreset = 'low_latency',
    token: str | None = None,
    *,
    _base_url: str = 'https://ipinfo.io',
) -> httpx.AsyncClient:
    options = (
        http
        .ClientOptions(base_url=_base_url)
        .performance_preset(performance)
        .use_common_headers()
    )
    if token:
        options = options.replace(params={'token': token})
    return http.new_async_httpx_client(options)


def to_legacy_ip_record(response_json: dict, ip: str) -> IpRecord:
    if response_json.get('bogon'):
        raise ValueError(f'{ip} is a bogon address')

    record_fields = {f.name for f in dc.fields(IpRecord)}
    kwargs: dict = {'ip': ip, 'extras': {}}
    for key, value in response_json.items():
        if key in record_fields:
            kwargs[key] = value
        else:
            kwargs['extras'][key] = value

    return IpRecord(**kwargs)


ip_info_retry = http.httpx_retry(
    attempts=3,
    reraise=True,
)


@dc.dataclass(slots=True)
class IPInfoClient:
    client: httpx.AsyncClient = dc.field(default_factory=ip_info_clientmaker)

    @ip_info_retry
    async def get_legacy_json(self, ip_address: str) -> dict[str, Any]:
        response = await self.client.get(f'/{ip_address}/json')
        http.validate_response(response)
        return response.json()

    @ip_info_retry
    async def get_lite_json(self, ip_address: str) -> dict[str, Any]:
        response = await self.client.get(f'/lite/{ip_address}/json')
        http.validate_response(response)
        return response.json()

    async def legacy_search(self, ip_address: str) -> IpRecord:
        response_json = await self.get_legacy_json(ip_address)
        return to_legacy_ip_record(response_json, ip_address)

    async def fetch_lite(self, ip_address: str) -> IpInfoLiteResponse:
        response = await self.get_lite_json(ip_address)
        return IpInfoLiteResponse.model_validate(response)

    async def lite_search(self, ip_address: str) -> IpLiteRecord:
        response_model = await self.fetch_lite(ip_address)
        return IpLiteRecord.parse_response(response_model)
