from typing import Any, Self

from reconflux.core import ReconfluxError


class DNSResolutionError(ReconfluxError):
    default_message = 'DNS resolution failed.'
    error_code = 'dns_resolution_error'

    @classmethod
    def query(
        cls,
        record_type: str | Any,
        qname: str
    ) -> Self:
        return cls(
            f'Failed to resolve DNS record {record_type} for {qname!r}.',
            context={
                'query_name': qname,
                'record_type': str(record_type),
            },
        )

    @classmethod
    def host(cls, hostname: str) -> Self:
        return cls(
            f'Failed to resolve host addresses for {hostname!r}.',
            context={'hostname': hostname},
        )

    @classmethod
    def canonical(cls, hostname: str) -> Self:
        return cls(
            f'Failed to determine canonical name for {hostname!r}.',
            context={'hostname': hostname},
        )


class ReverseLookupError(DNSResolutionError):
    default_message = 'Reverse DNS lookup failed.'
    error_code = 'reverse_lookup_error'
