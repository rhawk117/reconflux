import dataclasses as dc
from typing import ClassVar

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


def create_response_record(response: IpInfoLiteResponse) -> IpLiteRecord:
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

    return IpLiteRecord(
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


class IPInfoLegacyIntegration:
    """
    Legacy unauthenticated ipinfo.io integration.

    Queries ``https://ipinfo.io/{ip}/json`` with no token. Returns a minimal
    ``IpRecord`` with basic geolocation fields.
    """

    base_url: ClassVar[str] = 'https://ipinfo.io'

    def __init__(
        self,
        config: http.HTTPClientOptions | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._client = http.new_async_httpx_client(
            config,
            headers={
                'Accept': 'application/json',
                **(headers or {}),
            },
        )

    @http.httpx_retry(attempts=3)
    async def _fetch(self, ip: str) -> dict:
        response = await self._client.get(f'/{ip}/json')
        http.validate_response(response)
        return response.json()

    async def get_ip_record(self, ip: str) -> IpRecord:
        """
        Fetch the IP information for the given IP address.

        Returns
        -------
        IpRecord

        Raises
        ------
        ValueError
            If the IP address is a bogon address.
        """
        data = await self._fetch(ip)
        if data.get('bogon'):
            raise ValueError(f'{ip} is a bogon address')

        record_fields = {f.name for f in dc.fields(IpRecord)}
        kwargs: dict = {'ip': ip, 'extras': {}}
        for key, value in data.items():
            if key in record_fields:
                kwargs[key] = value
            else:
                kwargs['extras'][key] = value

        return IpRecord(**kwargs)


class IPInfoLiteIntegration:
    """
    IPInfo Lite integration using the free unauthenticated endpoint.

    Queries ``https://ipinfo.io/lite/{ip}/json``. No token is required.
    Returns an ``IpLiteRecord`` with enriched geolocation data including
    country metadata, continent info, and EU membership status.
    """

    base_url: ClassVar[str] = 'https://ipinfo.io'

    def __init__(
        self,
        config: http.HTTPClientOptions | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._client = http.new_async_httpx_client(
            config,
            headers={
                'Accept': 'application/json',
                **(headers or {}),
            },
        )

    @http.httpx_retry(attempts=3)
    async def _fetch(self, ip: str) -> IpInfoLiteResponse:
        response = await self._client.get(f'{self.base_url}/lite/{ip}/json')
        http.validate_response(response)
        return IpInfoLiteResponse.model_validate(response.json())

    async def get_ip_record(self, ip: str) -> IpLiteRecord:
        """
        Fetch the lite IP information for the given IP address.

        Returns
        -------
        IpLiteRecord

        Raises
        ------
        ValueError
            If the IP address is a bogon address.
        """
        response = await self._fetch(ip)
        if response.bogon:
            raise ValueError(f'{ip} is a bogon address')

        return create_response_record(response)
