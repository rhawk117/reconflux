import dataclasses as dc
from typing import Annotated, Any

import anyio
import typer
from rich.box import HEAVY_HEAD
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from reconflux.cli import utils as cli_utils
from reconflux.integrations.dns import (
    DNSBlocklistCollectionResult,
    DNSBlocklistResult,
    DNSCommandOptions,
    DNSIntegrationResult,
    DNSProvider,
    DNSRecordRow,
    DomainDNSResult,
    EmailDNSResult,
    ReverseDNSResult,
    build_command_options,
)

dns_app = typer.Typer()


DomainArgument = Annotated[
    str,
    typer.Argument(
        help='Domain to inspect.',
        metavar='DOMAIN',
    ),
]

IPArgument = Annotated[
    str,
    typer.Argument(
        help='IP address to reverse-resolve.',
        metavar='IP',
    ),
]

EmailArgument = Annotated[
    str,
    typer.Argument(
        help='Email address to inspect via MX, TXT, and DMARC lookups.',
        metavar='EMAIL',
    ),
]


DomainOption = Annotated[
    str,
    typer.Option(
        '--domain',
        help='Domain to inspect.',
        rich_help_panel='Target',
        show_default=True,
    ),
]

IPAddressOption = Annotated[
    str,
    typer.Option(
        '--ip',
        help='IP address to reverse-resolve.',
        rich_help_panel='Target',
        show_default=True,
    ),
]

EmailOption = Annotated[
    str,
    typer.Option(
        '--email',
        help='Email address to inspect via MX, TXT, and DMARC lookups.',
        rich_help_panel='Target',
        show_default=True,
    ),
]

NameserversOption = Annotated[
    list[str],
    typer.Option(
        '--nameserver',
        '-n',
        help='Custom resolver nameserver. Repeat to provide multiple values.',
        rich_help_panel='Resolver',
        show_default=True,
    ),
]

SearchDomainsOption = Annotated[
    list[str],
    typer.Option(
        '--search-domain',
        help='Custom search domain. Repeat to provide multiple values.',
        rich_help_panel='Resolver',
        show_default=True,
    ),
]

TimeoutOption = Annotated[
    float,
    typer.Option(
        '--timeout',
        min=0.0,
        help='Per-query timeout in seconds.',
        rich_help_panel='Resolver',
        show_default=True,
    ),
]

LifetimeOption = Annotated[
    float,
    typer.Option(
        '--lifetime',
        min=0.0,
        help='Resolver lifetime in seconds.',
        rich_help_panel='Resolver',
        show_default=True,
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
        show_default=True,
    ),
]

SearchOption = Annotated[
    bool,
    typer.Option(
        '--search/--no-search',
        help='Override resolver search-domain behavior.',
        rich_help_panel='Behavior',
        show_default=True,
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


def format_blocklist_status(result: DNSBlocklistResult) -> str:
    if result.listed is True:
        return 'LISTED'
    if result.listed is False:
        return 'clear'
    return 'unknown'


@dc.dataclass(slots=True)
class DNSConsoleComponents:
    def command_header(self, command: DNSCommandOptions) -> Panel:
        target_value = command.domain or command.ip_address or command.email or 'unknown'
        target_kind = (
            'Domain'
            if command.domain is not None
            else 'IP Address'
            if command.ip_address is not None
            else 'Email'
        )

        metadata_table = Table.grid(expand=True)
        metadata_table.add_column(justify='left')
        metadata_table.add_column(justify='left')
        metadata_table.add_row('Target Type', target_kind)
        metadata_table.add_row('Target', target_value)
        metadata_table.add_row('TCP', str(command.tcp))
        metadata_table.add_row(
            'Search',
            str(command.use_search_by_default),
        )
        metadata_table.add_row(
            'Blocklists',
            str(command.include_blocklists),
        )
        metadata_table.add_row('Fail Fast', str(command.fail_fast))
        metadata_table.add_row('Query Fan-out', str(command.query_count_hint))

        return Panel(metadata_table, title='DNS Lookup', border_style='cyan')

    def record_table(self, rows: list[DNSRecordRow], *, title: str) -> Table:
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

    def reverse_table(self, result: ReverseDNSResult) -> Table:
        table = Table(title='Reverse Lookup', box=HEAVY_HEAD)
        table.add_column('IP Address', no_wrap=True)
        table.add_column('Hostname', overflow='fold')

        if not result.rows:
            table.add_row(result.ip_address, 'No PTR hostnames returned.')
            return table

        for row in result.rows:
            table.add_row(row.ip_address, row.hostname)

        return table

    def blocklist_table(self, blocklist_result: DNSBlocklistCollectionResult) -> Table:
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


@dc.dataclass(slots=True)
class DNSConsole:
    console: Console = dc.field(default_factory=Console)
    components: DNSConsoleComponents = dc.field(default_factory=DNSConsoleComponents)

    def render_domain_result(self, result: DomainDNSResult) -> None:
        console_out = Group(
            self.components.record_table(
                result.rows,
                title=f'DNS Records for {result.domain}',
            ),
            cli_utils.error_table(result.queries.errors, title='Query Errors'),
        )
        self.console.print(console_out)

    def render_email_result(self, result: EmailDNSResult) -> None:
        summary_panel = Panel(
            Text.from_markup(
                f'[bold]Email:[/] {result.email}\n[bold]Domain:[/] {result.domain}'
            ),
            title='Email DNS Summary',
            border_style='magenta',
        )
        console_out = Group(
            summary_panel,
            self.components.record_table(result.rows, title='Mail-Related DNS Records'),
            cli_utils.error_table(result.queries.errors, title='Query Errors'),
        )
        self.console.print(console_out)

    def render_reverse_result(self, result: ReverseDNSResult) -> None:
        renderables: list[Any] = []

        if result.error is not None:
            renderables.append(
                Panel(
                    Text.from_markup(
                        f'[bold red]Reverse lookup failed:[/] {result.error}'
                    ),
                    title='Reverse Lookup Error',
                    border_style='red',
                )
            )

        renderables.append(self.components.reverse_table(result))

        if result.blocklists is not None:
            renderables.extend((
                self.components.blocklist_table(result.blocklists),
                cli_utils.error_table(
                    result.blocklists.results.errors,
                    title='Blocklist Task Errors',
                ),
            ))

        self.console.print(Group(*renderables))

    def render_header(self, command_options: DNSCommandOptions) -> None:
        self.console.print(self.components.command_header(command_options))

    def render_result(self, result: DNSIntegrationResult) -> None:
        if isinstance(result, DomainDNSResult):
            self.render_domain_result(result)
            return

        if isinstance(result, EmailDNSResult):
            self.render_email_result(result)
            return

        self.render_reverse_result(result)


async def run_dns_lookup(command_options: DNSCommandOptions) -> int:
    integration = DNSProvider(client_options=command_options)
    dnsconsole = DNSConsole()

    result = await integration.dispatch(
        command_options.request,
        search=command_options.use_search_by_default,
        tcp=command_options.tcp,
        include_blocklists=command_options.include_blocklists,
    )

    dnsconsole.render_header(command_options)
    dnsconsole.render_result(result)

    if isinstance(result, (DomainDNSResult, EmailDNSResult)):
        return 1 if result.queries.errors else 0

    if result.error is not None:
        return 1

    if result.blocklists is not None and result.blocklists.results.errors:
        return 1

    return 0


@dns_app.command('domain')
def dns_domain_command(
    domain: DomainArgument,
    *,
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
    fail_fast: FailFastOption = False,
) -> None:
    """Inspect DNS records for a domain."""
    try:
        command_options = build_command_options(
            domain=domain,
            ip_address=None,
            email=None,
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
            include_blocklists=False,
            fail_fast=fail_fast,
        )
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc

    with cli_utils.cli_exception_guard('DNS domain lookup failed'):
        exit_code = anyio.run(run_dns_lookup, command_options)

    raise typer.Exit(code=exit_code)


@dns_app.command('ip')
def dns_ip_command(
    ip_address: IPArgument,
    *,
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
    include_blocklists: IncludeBlocklistsOption = True,
    fail_fast: FailFastOption = False,
) -> None:
    """Reverse-resolve an IP address and check DNS blocklists."""
    try:
        command_options = build_command_options(
            domain=None,
            ip_address=ip_address,
            email=None,
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
            tcp=False,
            include_blocklists=include_blocklists,
            fail_fast=fail_fast,
        )
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc

    with cli_utils.cli_exception_guard('DNS IP lookup failed'):
        exit_code = anyio.run(run_dns_lookup, command_options)

    raise typer.Exit(code=exit_code)


@dns_app.command('email')
def dns_email_command(
    email: EmailArgument,
    *,
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
    fail_fast: FailFastOption = False,
) -> None:
    """Inspect MX, TXT, and DMARC records for an email address."""
    try:
        command_options = build_command_options(
            domain=None,
            ip_address=None,
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
            include_blocklists=False,
            fail_fast=fail_fast,
        )
    except Exception as exc:
        raise typer.BadParameter(str(exc)) from exc

    with cli_utils.cli_exception_guard('DNS email lookup failed'):
        exit_code = anyio.run(run_dns_lookup, command_options)

    raise typer.Exit(code=exit_code)


@dns_app.command('lookup')
def dns_lookup_command(
    *,
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
    """Run a DNS workflow for a domain, IP address, or email address."""
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

    with cli_utils.cli_exception_guard('DNS command failed'):
        exit_code = anyio.run(run_dns_lookup, command_options)

    raise typer.Exit(code=exit_code)
