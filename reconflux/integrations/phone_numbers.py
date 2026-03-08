import dataclasses as dc

import phonenumbers
from phonenumbers import carrier, geocoder

from reconflux.core import DataclassMixin
from reconflux.core.errors import ReconfluxValidationError


class PhoneNumberError(ReconfluxValidationError): ...


@dc.dataclass(slots=True)
class PhoneRecord(DataclassMixin):
    """
    Represents the result of a phone number lookup.
    """

    phone_number: str
    is_valid: bool
    e164: str | None = None
    country: str | None = None
    region: str | None = None
    operator: str | None = None


def get_phone_info(phone_number: str, lang: str = 'en') -> PhoneRecord:
    try:
        phone_obj = phonenumbers.parse(phone_number)
    except phonenumbers.NumberParseException as exc:
        raise PhoneNumberError(
            f'Error parsing phone number {phone_number}: {exc}'
        ) from exc

    kwargs: dict = {
        'e164': None,
        'country': None,
        'region': None,
        'operator': None,
    }
    if is_valid := phonenumbers.is_valid_number(phone_obj):
        kwargs.update(
            e164=phonenumbers.format_number(
                phone_obj,
                phonenumbers.PhoneNumberFormat.E164,
            ),
            country=geocoder.country_name_for_number(phone_obj, lang),
            region=geocoder.description_for_number(phone_obj, lang),
            operator=carrier.name_for_number(phone_obj, lang),
        )

    return PhoneRecord(phone_number=phone_number, is_valid=is_valid, **kwargs)
