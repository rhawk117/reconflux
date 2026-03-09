from __future__ import annotations

import dataclasses as dc
from typing import Annotated, Any

import anyio
import typer
from rich.box import HEAVY_HEAD, MINIMAL_DOUBLE_HEAD
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from reconflux.cli.utils import cli_exception_guard
from reconflux.integrations.certsh import CertshIntegration, SubdomainResult
from reconflux.integrations.ip_info import (
    IPInfoClient,
    IpLiteRecord,
    IpRecord,
    ip_info_clientmaker,
)

console = Console()
net_app = typer.Typer()


DomainArgument = Annotated[
    str,
    typer.Argument(
        help='Target domain to query.',
        metavar='DOMAIN',
    ),
]

IPArgument = Annotated[
    str,
    typer.Argument(
        help='Target IP address to look up.',
        metavar='IP',
    ),
]

TokenOption = Annotated[
    str,
    typer.Option(
        '--token',
        '-t',
        help='ipinfo.io API token for authenticated lookups.',
        rich_help_panel='Auth',
        envvar='IPINFO_TOKEN',
    ),
]

LiteOption = Annotated[
    bool,
    typer.Option(
        '--lite/--full',
        help='Use the free lite endpoint or the authenticated full endpoint.',
        rich_help_panel='Behavior',
    ),
]



@dc.dataclass(slots=True)
class NetRenderer:
    """Renders cert.sh and ipinfo.io results to the terminal via Rich."""
    console: Console = dc.field(default=console)


    @staticmethod
    def _kv_table(title: str) -> Table:
        table = Table(title=title, box=MINIMAL_DOUBLE_HEAD, show_header=False)
        table.add_column('Field', no_wrap=True, style='bold')
        table.add_column('Value', overflow='fold')
        return table

    @staticmethod
    def _row(table: Table, label: str, value: Any) -> None:
        table.add_row(label, str(value) if value is not None else '[dim]-[/dim]')

    def certsh(self, result: SubdomainResult) -> None:
        summary = Panel(
            Text.from_markup(
                f'[bold]Domain:[/]    {result.domain}\n'
                f'[bold]Subdomains:[/] {result.total}',
            ),
            title='cert.sh Subdomain Enumeration',
            border_style='cyan',
        )

        table = Table(
            title=f'Subdomains for {result.domain}',
            box=HEAVY_HEAD,
            show_lines=False,
        )
        table.add_column('#', justify='right', no_wrap=True, style='dim')
        table.add_column('Subdomain', overflow='fold')

        if not result.subdomains:
            table.add_row('-', '[italic]No subdomains found.[/italic]')
        else:
            for idx, subdomain in enumerate(result.subdomains, start=1):
                table.add_row(str(idx), subdomain)

        self.console.print(Group(summary, table))


    def ip_lite(self, record: IpLiteRecord) -> None:
        table = self._kv_table(f'IP Info (lite) \u2014 {record.ip}')

        flag_display: str | None = None
        if record.country_flag:
            flag_display = f'{record.country_flag.emoji}  {record.country_flag.unicode}'

        currency_display: str | None = None
        if record.country_currency:
            currency_display = (
                f'{record.country_currency.code} ({record.country_currency.symbol})'
            )

        continent_display: str | None = None
        if record.continent:
            continent_display = f'{record.continent.name} ({record.continent.code})'

        self._row(table, 'IP', record.ip)
        self._row(table, 'Hostname', record.hostname)
        self._row(table, 'City', record.city)
        self._row(table, 'Region', record.region)
        self._row(table, 'Country', record.country_name or record.country)
        self._row(table, 'Country Flag', flag_display)
        self._row(table, 'Currency', currency_display)
        self._row(table, 'Continent', continent_display)
        self._row(table, 'EU Member', 'Yes' if record.is_eu else 'No')
        self._row(table, 'Organisation', record.org)
        self._row(table, 'Postal', record.postal)
        self._row(table, 'Timezone', record.timezone)
        self._row(table, 'Coordinates', record.loc)
        self._row(table, 'Maps Link', record.maps_link)

        self.console.print(table)

    def ip_legacy(self, record: IpRecord) -> None:
        table = self._kv_table(f'IP Info \u2014 {record.ip}')

        self._row(table, 'IP', record.ip)
        self._row(table, 'City', record.city)
        self._row(table, 'Country', record.country)
        self._row(table, 'Organisation', record.org)
        self._row(table, 'Postal', record.postal)
        self._row(table, 'Timezone', record.timezone)
        self._row(table, 'Coordinates', record.location)
        self._row(table, 'Maps Link', record.maps_link)

        if record.extras:
            extras_table = Table(
                title='Additional Fields',
                box=MINIMAL_DOUBLE_HEAD,
                show_header=False,
            )
            extras_table.add_column('Field', style='dim')
            extras_table.add_column('Value', overflow='fold')
            for key, value in record.extras.items():
                extras_table.add_row(key, str(value))
            self.console.print(Group(table, extras_table))
            return

        self.console.print(table)

    def error(self, message: str, title: str = 'Unhandled Error') -> None:
        self.console.print(
            Panel(
                Text.from_markup(f'[bold red]{message}[/]'),
                title=title,
                border_style='red',
            )
        )


@dc.dataclass(slots=True)
class IntegrationRunner:
    renderer: NetRenderer = dc.field(default_factory=NetRenderer)

    async def run_certsh(self, domain: str) -> int:
        integration = CertshIntegration()
        result = await integration.get_subdomains(domain)
        self.renderer.certsh(result)
        return 0

    async def run_ip_info(
        self,
        ip_address: str,
        token: str | None,
        lite: bool,  # noqa: FBT001
    ) -> int:
        client = IPInfoClient(client=ip_info_clientmaker(token=token))

        if lite:
            record = await client.lite_search(ip_address)
            self.renderer.ip_lite(record)
        else:
            record_legacy = await client.legacy_search(ip_address)
            self.renderer.ip_legacy(record_legacy)

        return 0




@net_app.command('certsh')
def certsh_command(domain: DomainArgument) -> None:
    """Enumerate subdomains for DOMAIN via the cert.sh CT log API."""
    runner = IntegrationRunner()
    with cli_exception_guard('cert.sh lookup failed'):
        exit_code = anyio.run(runner.run_certsh, domain)

    raise typer.Exit(code=exit_code)


@net_app.command('ipinfo')
def ipinfo_command(
    *,
    ip_address: IPArgument,
    token: TokenOption | None = None,
    lite: LiteOption = True,
) -> None:
    """Look up geolocation and network metadata for IP_ADDRESS via ipinfo.io."""
    runner = IntegrationRunner()
    with cli_exception_guard('ipinfo lookup failed'):
        exit_code = anyio.run(
            runner.run_ip_info,
            ip_address,
            token,
            lite
        )
    raise typer.Exit(code=exit_code)
