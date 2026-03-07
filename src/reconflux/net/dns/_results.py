from __future__ import annotations

import dataclasses as dc
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from reconflux.core import DataclassMixin

if TYPE_CHECKING:
    from reconflux.net.dns._record_types import DNSRecordType


@dc.dataclass(slots=True)
class DNSAnswerRecord(DataclassMixin):
    value: str
    ttl: int | None = None
    record_type: DNSRecordType | str | None = None


@dc.dataclass(slots=True)
class DNSQueryResult(DataclassMixin):
    query_name: str
    record_type: DNSRecordType | str
    records: list[DNSAnswerRecord]
    canonical_name: str | None = None
    nameserver: str | None = None
    port: int | None = None
    response_time_ms: float | None = None
    answered_at: datetime = dc.field(
        default_factory=lambda: datetime.now(UTC)
    )

    @property
    def is_empty(self) -> bool:
        return not self.records

@dc.dataclass(slots=True)
class HostResolutionResult(DataclassMixin):
    hostname: str
    canonical_name: str | None
    ipv4_addresses: list[str]
    ipv6_addresses: list[str]

    @property
    def all_addresses(self) -> list[str]:
        return [*self.ipv4_addresses, *self.ipv6_addresses]

    @property
    def is_empty(self) -> bool:
        return not self.ipv4_addresses and not self.ipv6_addresses

@dc.dataclass(slots=True)
class ReverseLookupResult(DataclassMixin):
    ip_address: str
    hostnames: list[str]

    @property
    def primary_hostname(self) -> str | None:
        return self.hostnames[0] if self.hostnames else None

    @property
    def is_empty(self) -> bool:
        return not self.hostnames
