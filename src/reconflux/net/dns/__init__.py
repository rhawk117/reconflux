from reconflux.net.dns._client import DNSClient, new_async_dns_resolver
from reconflux.net.dns._errors import DNSResolutionError, ReverseLookupError
from reconflux.net.dns._options import DNSClientOptions
from reconflux.net.dns._record_types import DNSRecordType
from reconflux.net.dns._results import (
    DNSAnswerRecord,
    DNSQueryResult,
    HostResolutionResult,
    ReverseLookupResult,
)

__all__ = (
    'DNSAnswerRecord',
    'DNSClient',
    'DNSClientOptions',
    'DNSQueryResult',
    'DNSRecordType',
    'DNSResolutionError',
    'HostResolutionResult',
    'ReverseLookupError',
    'ReverseLookupResult',
    'new_async_dns_resolver',
)
