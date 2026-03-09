
from typing import Any

from pydantic import model_validator

from reconflux.integrations.dns._models import DNSLookupRequest
from reconflux.net.dns import DNSClientOptions


class DNSCommandOptions(DNSClientOptions):
    domain: str | None = None
    ip_address: str | None = None
    email: str | None = None
    tcp: bool = False
    include_blocklists: bool = True
    fail_fast: bool = False

    @model_validator(mode='after')
    def validate_target_selection(self) -> DNSCommandOptions:
        selected_targets = [
            value
            for value in (self.domain, self.ip_address, self.email)
            if value is not None
        ]
        if len(selected_targets) != 1:
            raise ValueError(
                'Exactly one of domain, ip_address, or email must be provided.'
            )
        return self

    @property
    def request(self) -> DNSLookupRequest:
        return DNSLookupRequest(
            domain=self.domain,
            ip_address=self.ip_address,
            email=self.email,
        )

    @property
    def query_count_hint(self) -> int:
        if self.domain is not None:
            return 9
        if self.email is not None:
            return 3
        if self.ip_address is not None and self.include_blocklists:
            return 5
        return 1


def build_command_options(
    *,
    domain: str | None,
    ip_address: str | None,
    email: str | None,
    nameservers: list[str] | None,
    search_domains: list[str] | None,
    timeout: float | None,
    lifetime: float | None,
    port: int | None,
    search: bool | None,
    rotate_nameservers: bool,
    retry_servfail: bool,
    use_edns: bool,
    edns_payload: int,
    disable_system_config: bool,
    tcp: bool,
    include_blocklists: bool,
    fail_fast: bool,
) -> DNSCommandOptions:
    command_options_kwargs: dict[str, Any] = {
        'domain': domain,
        'ip_address': ip_address,
        'email': email,
        'tcp': tcp,
        'include_blocklists': include_blocklists,
        'fail_fast': fail_fast,
        'rotate_nameservers': rotate_nameservers,
        'retry_servfail': retry_servfail,
        'use_edns': use_edns,
        'edns_payload': edns_payload,
        'configure_from_system': not disable_system_config,
    }

    if nameservers:
        command_options_kwargs['nameservers'] = nameservers

    if search_domains:
        command_options_kwargs['search_domains'] = tuple(search_domains)

    if timeout is not None:
        command_options_kwargs['timeout'] = timeout

    if lifetime is not None:
        command_options_kwargs['lifetime'] = lifetime

    if port is not None:
        command_options_kwargs['port'] = port

    if search is not None:
        command_options_kwargs['use_search_by_default'] = search

    return DNSCommandOptions(**command_options_kwargs)
