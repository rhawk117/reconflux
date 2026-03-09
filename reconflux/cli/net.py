from __future__ import annotations

import dataclasses as dc
from typing import Annotated, Any

import anyio
import typer
from rich.box import MINIMAL_DOUBLE_HEAD
from rich.console import Console, Group
from rich.table import Table

from reconflux.cli.utils import cli_exception_guard
from reconflux.integrations.ip_info import (
    IPInfoProvider,
    IpLiteRecord,
    IpRecord,
)
from reconflux.net.http import HttpPerformancePreset

console = Console()
net_app = typer.Typer()

OptimizationOption = Annotated[
    HttpPerformancePreset,
    typer.Option(
        '--optimization',
        help='The HttpPerformancePreset for the client used',
        rich_help_panel='Http',
    ),
]
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
    bool | None,
    typer.Option(
        '--lite/--full',
        help=(
            'Use the lite endpoint (requires token) or the unauthenticated legacy '
            'endpoint. Defaults to legacy when no token is provided.'
        ),
        rich_help_panel='Behavior',
    ),
]


def tablerow(table: Table, label: str, value: Any) -> None:
    table.add_row(label, str(value) if value is not None else '[dim]-[/dim]')


def keyvalue_table(title: str) -> Table:
    table = Table(title=title, box=MINIMAL_DOUBLE_HEAD, show_header=False)
    table.add_column('Field', no_wrap=True, style='bold')
    table.add_column('Value', overflow='fold')
    return table


@dc.dataclass(slots=True)
class IPInfoComponents:
    def ip_lite_result(self, record: IpLiteRecord) -> Table:
        table = keyvalue_table(f'IP Info (lite) \u2014 {record.ip}')

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

        table_contents = {
            'IP': record.ip,
            'Hostname': record.hostname,
            'City': record.city,
            'Region': record.region,
            'Country': record.country_name or record.country,
            'Country Flag': flag_display,
            'Currency': currency_display,
            'Continent': continent_display,
            'EU Member:': 'Yes' if record.is_eu else 'No',
            'Organisation': record.org,
            'Postal': record.postal,
            'Timezone': record.timezone,
            'Coordinates': record.loc,
            'Maps Link': record.maps_link,
        }
        for field, value in table_contents.items():
            tablerow(table, field, value)

        return table

    def legacy_result_group(self, record: IpRecord) -> Group:
        table = keyvalue_table(f'IP Info \u2014 {record.ip}')
        table_contents = {
            'IP': record.ip,
            'City': record.city,
            'Country': record.country,
            'Organisation': record.org,
            'Postal': record.postal,
            'Timezone': record.timezone,
            'Coordinates': record.location,
            'Maps Link': record.maps_link,
        }
        for key, value in table_contents.items():
            tablerow(table, key, value)

        extras_table = keyvalue_table('Additional Fields')
        if record.extras:
            for key, value in record.extras.items():
                extras_table.add_row(key, str(value))

        return Group(table, extras_table)

    def component_for(self, result: IpRecord | IpLiteRecord) -> Group | Table:
        return (
            self.legacy_result_group(result)
            if isinstance(result, IpRecord)
            else self.ip_lite_result(result)
        )


async def run_ip_info(
    ip_address: str,
    token: str | None,
    lite: bool | None,  # noqa: FBT001
    optimization: HttpPerformancePreset,
) -> int:
    ui_components = IPInfoComponents()
    console = Console()
    use_lite = lite if lite is not None else token is not None
    async with IPInfoProvider(token=token, performance=optimization) as ip_info:
        if use_lite:
            result = await ip_info.lite_search(ip_address)
        else:
            result = await ip_info.legacy_search(ip_address)

        console.print(ui_components.component_for(result))

    return 0


@net_app.command('ipinfo')
def ipinfo_command(
    *,
    ip_address: IPArgument,
    optimization: OptimizationOption = 'default',
    token: TokenOption | None = None,
    lite: LiteOption = None,
) -> None:
    """Look up geolocation and network metadata for IP_ADDRESS via ipinfo.io."""
    with cli_exception_guard('ipinfo lookup failed'):
        exit_code = anyio.run(
            run_ip_info,
            ip_address,
            token,
            lite,
            optimization,
        )

    raise typer.Exit(code=exit_code)
