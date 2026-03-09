from __future__ import annotations

from datetime import datetime
from ipaddress import IPv4Address, ip_address
from typing import Any

import httpx

from reconflux.net import http
from reconflux.net.rdap import (
    RDAPAutnumRecord,
    RDAPAutnumResponse,
    RDAPBootstrap,
    RDAPContact,
    RDAPDomainRecord,
    RDAPDomainResponse,
    RDAPEntityResponse,
    RDAPEventResponse,
    RDAPIPAddressResponse,
    RDAPLookupResult,
    RDAPNetworkRecord,
)


def _build_domain_lookup_url(
    base_url: str,
    domain_name: str,
) -> str:
    return f'{base_url.rstrip("/")}/domain/{domain_name}'


def _build_ip_lookup_url(
    base_url: str,
    address: str,
) -> str:
    return f'{base_url.rstrip("/")}/ip/{address}'


def _build_autnum_lookup_url(
    base_url: str,
    asn: int,
) -> str:
    return f'{base_url.rstrip("/")}/autnum/{asn}'


def _parse_vcard_value(
    card: list[Any],
) -> str | None:
    """
    Extract the value from a single jCard entry.

    Expected shape is usually:
    ['fn', {}, 'text', 'Example Name']
    """

    if len(card) < 4:
        return None

    value = card[3]
    if value is None:
        return None

    if isinstance(value, list):
        value_parts = [str(part).strip() for part in value if str(part).strip()]
        return ', '.join(value_parts) or None

    text = str(value).strip()
    return text or None


def _flatten_vcard(
    vcard_array: list[Any] | None,
) -> dict[str, str]:
    """
    Convert an RDAP vcardArray into a small flat mapping.

    Only extracts the fields Reconflux cares about.
    """

    if not vcard_array or len(vcard_array) != 2:
        return {}

    _, vcard_entries = vcard_array
    if not isinstance(vcard_entries, list):
        return {}

    flattened: dict[str, str] = {}

    for vcard_entry in vcard_entries:
        if not isinstance(vcard_entry, list) or not vcard_entry:
            continue

        field_name = str(vcard_entry[0]).strip().lower()
        field_value = _parse_vcard_value(vcard_entry)
        if not field_value:
            continue

        if field_name == 'fn':
            flattened['full_name'] = field_value
        elif field_name == 'org':
            flattened['organization'] = field_value
        elif field_name == 'email':
            flattened['email'] = field_value.removeprefix('mailto:')
        elif field_name == 'tel':
            normalized_phone = field_value.removeprefix('tel:')
            field_metadata = vcard_entry[1] if len(vcard_entry) > 1 else {}
            if 'fax' in str(field_metadata).lower():
                flattened['fax'] = normalized_phone
            elif 'phone' not in flattened:
                flattened['phone'] = normalized_phone
        elif field_name == 'adr':
            flattened['address'] = field_value
        elif field_name == 'contact-uri':
            flattened['contact_uri'] = field_value

    return flattened


def _normalize_contact(
    entity: RDAPEntityResponse,
) -> RDAPContact:
    flat_vcard = _flatten_vcard(entity.vcard_array)
    return RDAPContact(
        roles=tuple(entity.roles),
        full_name=flat_vcard.get('full_name'),
        organization=flat_vcard.get('organization'),
        email=flat_vcard.get('email'),
        phone=flat_vcard.get('phone'),
        fax=flat_vcard.get('fax'),
        address=flat_vcard.get('address'),
        contact_uri=flat_vcard.get('contact_uri'),
        country=entity.country,
        handle=entity.handle,
    )


def _pick_primary_contact(
    entities: list[RDAPEntityResponse],
    *,
    role: str,
) -> RDAPContact | None:
    target_role = role.casefold()

    for entity in entities:
        entity_roles = tuple(entity_role.casefold() for entity_role in entity.roles)
        if target_role in entity_roles:
            return _normalize_contact(entity)

    return None


def _pick_event_timestamp(
    events: list[RDAPEventResponse],
    *,
    action: str,
) -> datetime | None:
    target_action = action.casefold()

    for event in events:
        if not event.event_action or not event.event_date:
            continue

        if event.event_action.casefold() == target_action:
            return event.event_date

    return None


def _extract_last_changed_at(
    events: list[RDAPEventResponse],
) -> datetime | None:
    for candidate_action in ('last changed', 'last update of rdap database', 'updated'):
        timestamp = _pick_event_timestamp(events, action=candidate_action)
        if timestamp is not None:
            return timestamp

    return None


def _normalize_domain_record(
    query: str,
    response: RDAPDomainResponse,
) -> RDAPDomainRecord:
    return RDAPDomainRecord(
        query=query,
        handle=response.handle,
        ldh_name=response.ldh_name,
        unicode_name=response.unicode_name,
        statuses=tuple(response.status),
        nameservers=tuple(
            nameserver.ldh_name
            for nameserver in response.nameservers
            if nameserver.ldh_name
        ),
        registrant=_pick_primary_contact(response.entities, role='registrant'),
        registrar=_pick_primary_contact(response.entities, role='registrar'),
        administrative=_pick_primary_contact(response.entities, role='administrative'),
        technical=_pick_primary_contact(response.entities, role='technical'),
        abuse=_pick_primary_contact(response.entities, role='abuse'),
        billing=_pick_primary_contact(response.entities, role='billing'),
        created_at=_pick_event_timestamp(response.events, action='registration'),
        updated_at=_pick_event_timestamp(response.events, action='last changed'),
        expires_at=_pick_event_timestamp(response.events, action='expiration'),
        last_changed_at=_extract_last_changed_at(response.events),
        raw_entities_count=len(response.entities),
    )


def _normalize_ip_network_record(
    query: str,
    response: RDAPIPAddressResponse,
) -> RDAPNetworkRecord:
    return RDAPNetworkRecord(
        query=query,
        handle=response.handle,
        start_address=response.start_address,
        end_address=response.end_address,
        ip_version=response.ip_version,
        network_name=response.name,
        network_type=response.type,
        country=response.country,
        statuses=tuple(response.status),
        abuse=_pick_primary_contact(response.entities, role='abuse'),
        technical=_pick_primary_contact(response.entities, role='technical'),
        administrative=_pick_primary_contact(response.entities, role='administrative'),
        created_at=_pick_event_timestamp(response.events, action='registration'),
        updated_at=_pick_event_timestamp(response.events, action='last changed'),
        last_changed_at=_extract_last_changed_at(response.events),
        raw_entities_count=len(response.entities),
    )


def _normalize_autnum_record(
    query: str,
    response: RDAPAutnumResponse,
) -> RDAPAutnumRecord:
    return RDAPAutnumRecord(
        query=query,
        handle=response.handle,
        start_autnum=response.start_autnum,
        end_autnum=response.end_autnum,
        name=response.name,
        autnum_type=response.type,
        country=response.country,
        statuses=tuple(response.status),
        abuse=_pick_primary_contact(response.entities, role='abuse'),
        technical=_pick_primary_contact(response.entities, role='technical'),
        administrative=_pick_primary_contact(response.entities, role='administrative'),
        created_at=_pick_event_timestamp(response.events, action='registration'),
        updated_at=_pick_event_timestamp(response.events, action='last changed'),
        last_changed_at=_extract_last_changed_at(response.events),
        raw_entities_count=len(response.entities),
    )





def rdap_clientmaker(
    performance: http.HttpPerformancePreset = 'low_latency',
    options: http.ClientOptions | None = None,
) -> httpx.AsyncClient:
    client_options = options or http.ClientOptions().performance_preset(
        performance
    ).use_common_headers().replace(follow_redirects=True)
    return http.new_async_httpx_client(client_options)




class RDAPProvider(http.HTTPIntegration):
    """
    Async-first RDAP client built on Reconflux HTTP primitives.

    Returns both raw Pydantic response models and normalized framework-friendly
    record types.
    """

    def __init__(
        self,
        performance: http.HttpPerformancePreset = 'low_latency',
        options: http.ClientOptions | None = None,
        *,
        max_referral_depth: int = 6,
    ) -> None:
        super().__init__(performance, options or http.ClientOptions())
        self._max_referral_depth = max_referral_depth
        self.bootstrap = RDAPBootstrap(self.client)

    async def fetch_domain(
        self,
        domain_name: str,
    ) -> RDAPLookupResult[RDAPDomainRecord, RDAPDomainResponse]:
        bootstrap_base_url = await self.bootstrap.resolve_domain_url(domain_name)
        lookup_url = _build_domain_lookup_url(bootstrap_base_url, domain_name)
        resolved_url, payload = await self.bootstrap.resolve_authoritative_json(
            lookup_url,
            target=domain_name,
        )

        response_model = RDAPDomainResponse.model_validate(payload)
        record = _normalize_domain_record(domain_name, response_model)

        return RDAPLookupResult(
            query=domain_name,
            resolved_url=resolved_url,
            kind='domain',
            record=record,
            response=response_model,
        )

    async def fetch_ip(
        self,
        address: str,
    ) -> RDAPLookupResult[RDAPNetworkRecord, RDAPIPAddressResponse]:
        bootstrap_base_url = await self.bootstrap.resolve_ip_url(address)
        lookup_url = _build_ip_lookup_url(bootstrap_base_url, address)
        resolved_url, payload = await self.bootstrap.resolve_authoritative_json(
            lookup_url,
            target=address,
        )
        response_model = RDAPIPAddressResponse.model_validate(payload)
        record = _normalize_ip_network_record(address, response_model)
        address_kind = 'ipv4' if isinstance(ip_address(address), IPv4Address) else 'ipv6'
        return RDAPLookupResult(
            query=address,
            resolved_url=resolved_url,
            kind=address_kind,
            record=record,
            response=response_model,
        )

    async def fetch_asn(
        self,
        asn: int,
    ) -> RDAPLookupResult[RDAPAutnumRecord, RDAPAutnumResponse]:
        bootstrap_base_url = await self.bootstrap.resolve_asn_url(asn)
        lookup_url = _build_autnum_lookup_url(bootstrap_base_url, asn)
        resolved_url, payload = await self.bootstrap.resolve_authoritative_json(
            lookup_url,
            target=f'autnum/{asn}',
        )
        response_model = RDAPAutnumResponse.model_validate(payload)
        record = _normalize_autnum_record(str(asn), response_model)
        return RDAPLookupResult(
            query=str(asn),
            resolved_url=resolved_url,
            kind='autnum',
            record=record,
            response=response_model,
        )
