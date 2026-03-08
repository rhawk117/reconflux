from __future__ import annotations

import dataclasses as dc
from typing import TYPE_CHECKING, Any

from pydantic import PositiveFloat, PositiveInt

from reconflux.core import DataclassMixin, ReconfluxModel

if TYPE_CHECKING:
    from datetime import datetime


class TLSClientOptions(ReconfluxModel):
    port: PositiveInt = 443
    timeout: PositiveFloat = 10.0
    verify: bool = True

    @classmethod
    def balanced(cls) -> TLSClientOptions:
        return cls()

    @classmethod
    def low_latency(cls) -> TLSClientOptions:
        return cls(timeout=5.0)

    @classmethod
    def insecure(cls) -> TLSClientOptions:
        return cls(verify=False)


@dc.dataclass(slots=True)
class TLSCertificateResult(DataclassMixin):
    hostname: str
    port: int
    issued_to: str | None
    issued_by: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    serial_number: str | None
    version: int | None
    subject_alternative_names: list[str] = dc.field(default_factory=list)
    raw_certificate: dict[str, Any] | None = None

    @property
    def is_validity_known(self) -> bool:
        return self.valid_from is not None and self.valid_until is not None
