from collections.abc import Sequence
from typing import Self

from pydantic import PositiveFloat, PositiveInt

from reconflux.core import ReconfluxModel


class DNSClientOptions(ReconfluxModel):
    timeout: PositiveFloat = 3.0
    lifetime: PositiveFloat = 5.0
    use_search_by_default: bool = False
    configure_from_system: bool = True
    rotate_nameservers: bool = False
    use_edns: bool = False
    edns_payload: PositiveInt = 1232
    retry_servfail: bool = False
    nameservers: list[str] | None = None
    search_domains: Sequence[str] | None = None
    port: PositiveInt = 53

    @classmethod
    def balanced(cls) -> Self:
        return cls()

    @classmethod
    def low_latency(cls) -> Self:
        return cls(
            timeout=2.0,
            lifetime=3.0,
            use_search_by_default=False,
            configure_from_system=True,
        )

    @classmethod
    def high_reliability(cls) -> Self:
        return cls(
            timeout=4.0,
            lifetime=8.0,
            retry_servfail=True,
            rotate_nameservers=True,
            use_search_by_default=False,
            configure_from_system=True,
        )

    @classmethod
    def with_nameservers(
        cls,
        nameservers: Sequence[str],
        *,
        timeout: float = 3.0,
        lifetime: float = 5.0,
    ) -> Self:
        return cls(
            nameservers=list(nameservers),
            timeout=timeout,
            lifetime=lifetime,
            configure_from_system=False,
        )
