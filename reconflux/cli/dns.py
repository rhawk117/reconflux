from __future__ import annotations

from typing import Annotated, Any

import anyio
import typer
from pydantic import model_validator
from rich.box import HEAVY_HEAD, MINIMAL_DOUBLE_HEAD
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from reconflux.integrations.dns import (
    DNSBlocklistCollectionResult,
    DNSBlocklistResult,
    DNSIntegration,
    DNSLookupRequest,
    DNSRecordRow,
    DomainDNSResult,
    EmailDNSResult,
    ReverseDNSResult,
)
from reconflux.net.dns import DNSClientOptions

console = Console()

app = typer.Typer(
    name='reconflux',
    no_args_is_help=True,
    rich_markup_mode='rich',
    help='Reconflux terminal interface.',
)

dns_app = typer.Typer(
    name='dns',
    no_args_is_help=True,
    help='Run DNS reconnaissance workflows.',
)

app.add_typer(dns_app, name='dns')


DomainOption = Annotated[
    str,
    typer.Option(
        '--domain',
        help='Domain to inspect.',
        rich_help_panel='Target',
    ),
]

IPAddressOption = Annotated[
    str,
    typer.Option(
        '--ip',
        help='IP address to reverse-resolve.',
        rich_help_panel='Target',
    ),
]

EmailOption = Annotated[
    str,
    typer.Option(
        '--email',
        help='Email address to inspect via MX, TXT, and DMARC lookups.',
        rich_help_panel='Target',
    ),
]

NameserversOption = Annotated[
    list[str],
    typer.Option(
        '--nameserver',
        '-n',
        help='Custom resolver nameserver. Repeat to provide multiple values.',
        rich_help_panel='Resolver',
    ),
]

SearchDomainsOption = Annotated[
    list[str],
    typer.Option(
        '--search-domain',
        help='Custom search domain. Repeat to provide multiple values.',
        rich_help_panel='Resolver',
    ),
]

TimeoutOption = Annotated[
    float,
    typer.Option(
        '--timeout',
        min=0.0,
        help='Per-query timeout in seconds.',
        rich_help_panel='Resolver',
    ),
]

LifetimeOption = Annotated[
    float,
    typer.Option(
        '--lifetime',
        min=0.0,
        help='Resolver lifetime in seconds.',
        rich_help_panel='Resolver',
    ),
]

PortOption = Annotated[
    int,
    typer.Option(
        '--port',
        min=1,
        max=65535,
        help='Resolver port override.',
        rich_help_panel='Resolver',
    ),
]

SearchOption = Annotated[
    bool,
    typer.Option(
        '--search/--no-search',
        help='Override resolver search-domain behavior.',
        rich_help_panel='Behavior',
    ),
]

RotateNameserversOption = Annotated[
    bool,
    typer.Option(
        '--rotate-nameservers',
        help='Rotate across configured nameservers.',
        rich_help_panel='Resolver',
    ),
]

RetryServfailOption = Annotated[
    bool,
    typer.Option(
        '--retry-servfail',
        help='Retry SERVFAIL responses.',
        rich_help_panel='Resolver',
    ),
]

UseEDNSOption = Annotated[
    bool,
    typer.Option(
        '--use-edns/--no-edns',
        help='Enable or disable EDNS support.',
        rich_help_panel='Resolver',
    ),
]

EDNSPayloadOption = Annotated[
    int,
    typer.Option(
        '--edns-payload',
        min=0,
        help='EDNS payload size.',
        rich_help_panel='Resolver',
    ),
]

DisableSystemConfigOption = Annotated[
    bool,
    typer.Option(
        '--disable-system-config',
        help='Do not load resolver configuration from the operating system.',
        rich_help_panel='Resolver',
    ),
]

TCPOption = Annotated[
    bool,
    typer.Option(
        '--tcp/--udp',
        help='Force TCP or use UDP for record queries.',
        rich_help_panel='Behavior',
    ),
]

IncludeBlocklistsOption = Annotated[
    bool,
    typer.Option(
        '--blocklists/--no-blocklists',
        help='Enable or disable DNSBL checks for IP lookups.',
        rich_help_panel='Behavior',
    ),
]

FailFastOption = Annotated[
    bool,
    typer.Option(
        '--fail-fast/--collect-errors',
        help='Stop on first task error or collect task errors.',
        rich_help_panel='Behavior',
    ),
]


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


def build_client_options(command_options: DNSCommandOptions) -> DNSClientOptions:
    return DNSClientOptions(
        timeout=command_options.timeout,
        lifetime=command_options.lifetime,
        use_search_by_default=command_options.use_search_by_default,
        configure_from_system=command_options.configure_from_system,
        rotate_nameservers=command_options.rotate_nameservers,
        use_edns=command_options.use_edns,
        edns_payload=command_options.edns_payload,
        retry_servfail=command_options.retry_servfail,
        nameservers=command_options.nameservers,
        search_domains=command_options.search_domains,
        port=command_options.port,
    )


def render_header_panel(command_options: DNSCommandOptions) -> Panel:
    target_value = (
        command_options.domain
        or command_options.ip_address
        or command_options.email
        or 'unknown'
    )
    target_kind = (
        'Domain'
        if command_options.domain is not None
        else 'IP Address'
        if command_options.ip_address is not None
        else 'Email'
    )

    metadata_table = Table.grid(expand=True)
    metadata_table.add_column(justify='left')
    metadata_table.add_column(justify='left')
    metadata_table.add_row('Target Type', target_kind)
    metadata_table.add_row('Target', target_value)
    metadata_table.add_row('TCP', str(command_options.tcp))
    metadata_table.add_row(
        'Search',
        str(command_options.use_search_by_default),
    )
    metadata_table.add_row(
        'Blocklists',
        str(command_options.include_blocklists),
    )
    metadata_table.add_row('Fail Fast', str(command_options.fail_fast))
    metadata_table.add_row('Query Fan-out', str(command_options.query_count_hint))

    return Panel(metadata_table, title='DNS Lookup', border_style='cyan')


def build_record_table(rows: list[DNSRecordRow], *, title: str) -> Table:
    table = Table(title=title, box=HEAVY_HEAD, show_lines=False)
    table.add_column('Query Name', overflow='fold')
    table.add_column('Type', no_wrap=True)
    table.add_column('Value', overflow='fold')
    table.add_column('TTL', justify='right', no_wrap=True)
    table.add_column('Canonical', overflow='fold')
    table.add_column('Nameserver', overflow='fold')
    table.add_column('Port', justify='right', no_wrap=True)
    table.add_column('Response (ms)', justify='right', no_wrap=True)

    if not rows:
        table.add_row('-', '-', 'No records returned.', '-', '-', '-', '-', '-')
        return table

    for row in rows:
        table.add_row(
            row.query_name,
            row.record_type,
            row.value,
            '' if row.ttl is None else str(row.ttl),
            row.canonical_name or '',
            row.nameserver or '',
            '' if row.port is None else str(row.port),
            '' if row.response_time_ms is None else f'{row.response_time_ms:.2f}',
        )

    return table


def build_error_table(errors: dict[str, str], *, title: str) -> Table:
    table = Table(title=title, box=MINIMAL_DOUBLE_HEAD)
    table.add_column('Task')
    table.add_column('Error', overflow='fold')

    if not errors:
        table.add_row('None', '')
        return table

    for task_name, error_text in errors.items():
        table.add_row(task_name, error_text)

    return table


def build_reverse_table(result: ReverseDNSResult) -> Table:
    table = Table(title='Reverse Lookup', box=HEAVY_HEAD)
    table.add_column('IP Address', no_wrap=True)
    table.add_column('Hostname', overflow='fold')

    if not result.rows:
        table.add_row(result.ip_address, 'No PTR hostnames returned.')
        return table

    for row in result.rows:
        table.add_row(row.ip_address, row.hostname)

    return table


def format_blocklist_status(result: DNSBlocklistResult) -> str:
    if result.listed is True:
        return 'LISTED'
    if result.listed is False:
        return 'clear'
    return 'unknown'


def build_blocklist_table(blocklist_result: DNSBlocklistCollectionResult) -> Table:
    table = Table(title='DNS Blocklists', box=HEAVY_HEAD)
    table.add_column('Zone', overflow='fold')
    table.add_column('Listed', no_wrap=True)
    table.add_column('Records', overflow='fold')
    table.add_column('Error', overflow='fold')

    ordered_results = sorted(
        blocklist_result.results.results.values(),
        key=lambda blocklist_result_item: blocklist_result_item.blocklist.zone,
    )

    if not ordered_results:
        table.add_row('-', '-', 'No blocklist results returned.', '')
        return table

    for result in ordered_results:
        table.add_row(
            result.blocklist.zone,
            format_blocklist_status(result),
            ', '.join(result.records) if result.records else '',
            result.error or '',
        )

    return table


def render_domain_result(result: DomainDNSResult) -> None:
    console.print(
        Group(
            build_record_table(
                result.rows,
                title=f'DNS Records for {result.domain}',
            ),
            build_error_table(result.queries.errors, title='Query Errors'),
        )
    )


def render_email_result(result: EmailDNSResult) -> None:
    summary_panel = Panel(
        Text.from_markup(
            f'[bold]Email:[/] {result.email}\n[bold]Domain:[/] {result.domain}'
        ),
        title='Email DNS Summary',
        border_style='magenta',
    )

    console.print(
        Group(
            summary_panel,
            build_record_table(
                result.rows,
                title='Mail-Related DNS Records',
            ),
            build_error_table(result.queries.errors, title='Query Errors'),
        )
    )


def render_ip_result(result: ReverseDNSResult) -> None:
    renderables: list[Any] = []

    if result.error is not None:
        renderables.append(
            Panel(
                Text.from_markup(f'[bold red]Reverse lookup failed:[/] {result.error}'),
                title='Reverse Lookup Error',
                border_style='red',
            )
        )

    renderables.append(build_reverse_table(result))

    if result.blocklists is not None:
        renderables.append(build_blocklist_table(result.blocklists))
        renderables.append(
            build_error_table(
                result.blocklists.results.errors,
                title='Blocklist Task Errors',
            )
        )

    console.print(Group(*renderables))


def render_dispatch_result(
    result: DomainDNSResult | EmailDNSResult | ReverseDNSResult,
) -> None:
    if isinstance(result, DomainDNSResult):
        render_domain_result(result)
        return

    if isinstance(result, EmailDNSResult):
        render_email_result(result)
        return

    render_ip_result(result)


async def run_dns_lookup(command_options: DNSCommandOptions) -> int:
    integration = DNSIntegration(client_options=build_client_options(command_options))

    result = await integration.dispatch(
        command_options.request,
        search=command_options.use_search_by_default,
        tcp=command_options.tcp,
        include_blocklists=command_options.include_blocklists,
    )

    console.print(render_header_panel(command_options))
    render_dispatch_result(result)

    if isinstance(result, DomainDNSResult):
        return 1 if result.queries.errors else 0

    if isinstance(result, EmailDNSResult):
        return 1 if result.queries.errors else 0

    if result.error is not None:
        return 1

    if result.blocklists is not None and result.blocklists.results.errors:
        return 1

    return 0


@dns_app.command('lookup')
def dns_lookup_command(
    domain: DomainOption | None = None,
    ip_address: IPAddressOption | None = None,
    email: EmailOption | None = None,
    nameservers: NameserversOption | None = None,
    search_domains: SearchDomainsOption | None = None,
    timeout: TimeoutOption | None = None,
    lifetime: LifetimeOption | None = None,
    port: PortOption | None = None,
    search: SearchOption | None = None,
    rotate_nameservers: RotateNameserversOption = False,
    retry_servfail: RetryServfailOption = False,
    use_edns: UseEDNSOption = False,
    edns_payload: EDNSPayloadOption = 1232,
    disable_system_config: DisableSystemConfigOption = False,
    tcp: TCPOption = False,
    include_blocklists: IncludeBlocklistsOption = True,
    fail_fast: FailFastOption = False,
) -> None:
    """Run a DNS workflow and render Rich tables."""
    try:
        command_options = build_command_options(
            domain=domain,
            ip_address=ip_address,
            email=email,
            nameservers=nameservers,
            search_domains=search_domains,
            timeout=timeout,
            lifetime=lifetime,
            port=port,
            search=search,
            rotate_nameservers=rotate_nameservers,
            retry_servfail=retry_servfail,
            use_edns=use_edns,
            edns_payload=edns_payload,
            disable_system_config=disable_system_config,
            tcp=tcp,
            include_blocklists=include_blocklists,
            fail_fast=fail_fast,
        )
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc

    try:
        exit_code = anyio.run(run_dns_lookup, command_options)
    except KeyboardInterrupt as exc:
        raise typer.Exit(code=130) from exc
    except Exception as exc:
        console.print(
            Panel(
                Text.from_markup(f'[bold red]DNS command failed:[/] {exc!r}'),
                title='Unhandled Error',
                border_style='red',
            )
        )
        raise typer.Exit(code=1) from exc

    raise typer.Exit(code=exit_code)


if __name__ == '__main__':
    app()
