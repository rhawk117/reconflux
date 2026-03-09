from __future__ import annotations

import dataclasses as dc
from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, HttpUrl

from reconflux.core import DataclassMixin, ReconfluxModel

type RDAPObjectClassName = Literal[
    'domain',
    'entity',
    'nameserver',
    'autnum',
    'ip network',
]

type RDAPLookupKind = Literal[
    'domain',
    'ipv4',
    'ipv6',
    'autnum',
]


class RDAPLinkResponse(ReconfluxModel):
    """Raw RDAP link object."""

    model_config = ConfigDict(
        extra='ignore',
        populate_by_name=True,
        use_enum_values=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    value: HttpUrl | None = None
    rel: str | None = None
    href: HttpUrl | None = None
    type: str | None = None
    title: str | None = None


class RDAPEventResponse(ReconfluxModel):
    """Raw RDAP event object."""

    model_config = ConfigDict(
        extra='ignore',
        populate_by_name=True,
        use_enum_values=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    event_action: str | None = Field(default=None, alias='eventAction')
    event_date: datetime | None = Field(default=None, alias='eventDate')


class RDAPNoticeResponse(ReconfluxModel):
    """Raw RDAP notice or remark object."""

    model_config = ConfigDict(
        extra='ignore',
        populate_by_name=True,
        use_enum_values=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    title: str | None = None
    description: list[str] = Field(default_factory=list)
    links: list[RDAPLinkResponse] = Field(default_factory=list)


class RDAPNameServerResponse(ReconfluxModel):
    """Raw RDAP nameserver object."""

    model_config = ConfigDict(
        extra='ignore',
        populate_by_name=True,
        use_enum_values=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    object_class_name: str | None = Field(default=None, alias='objectClassName')
    ldh_name: str | None = Field(default=None, alias='ldhName')
    unicode_name: str | None = Field(default=None, alias='unicodeName')


class RDAPEntityResponse(ReconfluxModel):
    """Raw RDAP entity object."""

    model_config = ConfigDict(
        extra='ignore',
        populate_by_name=True,
        use_enum_values=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    object_class_name: str | None = Field(default=None, alias='objectClassName')
    handle: str | None = None
    roles: list[str] = Field(default_factory=list)
    country: str | None = None
    links: list[RDAPLinkResponse] = Field(default_factory=list)
    events: list[RDAPEventResponse] = Field(default_factory=list)
    entities: list[RDAPEntityResponse] = Field(default_factory=list)
    vcard_array: list[Any] | None = Field(default=None, alias='vcardArray')


class RDAPDomainResponse(ReconfluxModel):
    """Raw RDAP domain response."""

    model_config = ConfigDict(
        extra='ignore',
        populate_by_name=True,
        use_enum_values=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    object_class_name: str | None = Field(default=None, alias='objectClassName')
    handle: str | None = None
    ldh_name: str | None = Field(default=None, alias='ldhName')
    unicode_name: str | None = Field(default=None, alias='unicodeName')
    status: list[str] = Field(default_factory=list)
    nameservers: list[RDAPNameServerResponse] = Field(default_factory=list)
    entities: list[RDAPEntityResponse] = Field(default_factory=list)
    events: list[RDAPEventResponse] = Field(default_factory=list)
    links: list[RDAPLinkResponse] = Field(default_factory=list)
    notices: list[RDAPNoticeResponse] = Field(default_factory=list)
    remarks: list[RDAPNoticeResponse] = Field(default_factory=list)


class RDAPIPAddressResponse(ReconfluxModel):
    """Raw RDAP IP network response."""

    model_config = ConfigDict(
        extra='ignore',
        populate_by_name=True,
        use_enum_values=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    object_class_name: str | None = Field(default=None, alias='objectClassName')
    handle: str | None = None
    start_address: str | None = Field(default=None, alias='startAddress')
    end_address: str | None = Field(default=None, alias='endAddress')
    ip_version: str | None = Field(default=None, alias='ipVersion')
    name: str | None = None
    type: str | None = None
    country: str | None = None
    parent_handle: str | None = Field(default=None, alias='parentHandle')
    status: list[str] = Field(default_factory=list)
    entities: list[RDAPEntityResponse] = Field(default_factory=list)
    events: list[RDAPEventResponse] = Field(default_factory=list)
    links: list[RDAPLinkResponse] = Field(default_factory=list)
    notices: list[RDAPNoticeResponse] = Field(default_factory=list)
    remarks: list[RDAPNoticeResponse] = Field(default_factory=list)


class RDAPAutnumResponse(ReconfluxModel):
    """Raw RDAP autnum response."""

    model_config = ConfigDict(
        extra='ignore',
        populate_by_name=True,
        use_enum_values=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    object_class_name: str | None = Field(default=None, alias='objectClassName')
    handle: str | None = None
    start_autnum: int | None = Field(default=None, alias='startAutnum')
    end_autnum: int | None = Field(default=None, alias='endAutnum')
    name: str | None = None
    type: str | None = None
    country: str | None = None
    status: list[str] = Field(default_factory=list)
    entities: list[RDAPEntityResponse] = Field(default_factory=list)
    events: list[RDAPEventResponse] = Field(default_factory=list)
    links: list[RDAPLinkResponse] = Field(default_factory=list)
    notices: list[RDAPNoticeResponse] = Field(default_factory=list)
    remarks: list[RDAPNoticeResponse] = Field(default_factory=list)


RDAPEntityResponse.model_rebuild()


@dc.dataclass(slots=True)
class RDAPContact(DataclassMixin):
    """Normalized RDAP contact details."""

    roles: tuple[str, ...] = ()
    full_name: str | None = None
    organization: str | None = None
    email: str | None = None
    phone: str | None = None
    fax: str | None = None
    address: str | None = None
    contact_uri: str | None = None
    country: str | None = None
    handle: str | None = None


@dc.dataclass(slots=True)
class RDAPEvent(DataclassMixin):
    """Normalized RDAP event."""

    action: str
    timestamp: datetime


@dc.dataclass(slots=True)
class RDAPDomainRecord(DataclassMixin):
    """Normalized domain RDAP record."""

    query: str
    handle: str | None = None
    ldh_name: str | None = None
    unicode_name: str | None = None
    statuses: tuple[str, ...] = ()
    nameservers: tuple[str, ...] = ()
    registrant: RDAPContact | None = None
    registrar: RDAPContact | None = None
    administrative: RDAPContact | None = None
    technical: RDAPContact | None = None
    abuse: RDAPContact | None = None
    billing: RDAPContact | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    last_changed_at: datetime | None = None
    raw_entities_count: int = 0


@dc.dataclass(slots=True)
class RDAPNetworkRecord(DataclassMixin):
    """Normalized network RDAP record."""

    query: str
    handle: str | None = None
    start_address: str | None = None
    end_address: str | None = None
    ip_version: str | None = None
    network_name: str | None = None
    network_type: str | None = None
    country: str | None = None
    statuses: tuple[str, ...] = ()
    abuse: RDAPContact | None = None
    technical: RDAPContact | None = None
    administrative: RDAPContact | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_changed_at: datetime | None = None
    raw_entities_count: int = 0


@dc.dataclass(slots=True)
class RDAPAutnumRecord(DataclassMixin):
    """Normalized ASN RDAP record."""

    query: str
    handle: str | None = None
    start_autnum: int | None = None
    end_autnum: int | None = None
    name: str | None = None
    autnum_type: str | None = None
    country: str | None = None
    statuses: tuple[str, ...] = ()
    abuse: RDAPContact | None = None
    technical: RDAPContact | None = None
    administrative: RDAPContact | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_changed_at: datetime | None = None
    raw_entities_count: int = 0


@dc.dataclass(slots=True)
class RDAPLookupResult[Record, Response: ReconfluxModel](DataclassMixin):
    """Container for raw and normalized RDAP output."""

    query: str
    resolved_url: str
    kind: RDAPLookupKind
    record: Record
    response: Response
