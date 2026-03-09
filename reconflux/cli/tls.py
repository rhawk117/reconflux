from __future__ import annotations

import dataclasses as dc
from typing import Annotated

import anyio
import typer
from rich.box import MINIMAL_DOUBLE_HEAD
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from reconflux.cli import utils as cli_utils
from reconflux.integrations.tls import TLSBatchResult, TLSIntegration
from reconflux.net.tls import TLSCertificateResult, TLSClientOptions

tls_app = typer.Typer()


HostArgument = Annotated[
    str,
    typer.Argument(
        help='Hostname to inspect.',
        metavar='HOST',
    ),
]

HostsOption = Annotated[
    list[str],
    typer.Option(
        '--host',
        '-H',
        help='Hostname to inspect. Repeat to provide multiple targets.',
        rich_help_panel='Targets',
    ),
]

PortOption = Annotated[
    int,
    typer.Option(
        '--port',
        '-p',
        min=1,
        max=65535,
        help='TCP port to connect on.',
        rich_help_panel='TLS Options',
        show_default=True,
    ),
]

TimeoutOption = Annotated[
    float,
    typer.Option(
        '--timeout',
        min=0.01,
        help='Socket connection timeout in seconds.',
        rich_help_panel='TLS Options',
        show_default=True,
    ),
]

VerifyOption = Annotated[
    bool,
    typer.Option(
        '--verify/--no-verify',
        help='Verify the certificate chain against system trust store.',
        rich_help_panel='TLS Options',
    ),
]

ConcurrencyOption = Annotated[
    int | None,
    typer.Option(
        '--concurrency',
        '-c',
        min=1,
        help='Maximum simultaneous connections. Omit for no cap.',
        rich_help_panel='Behavior',
    ),
]

FailFastOption = Annotated[
    bool,
    typer.Option(
        '--fail-fast/--collect-errors',
        help='Abort on the first failure or collect per-host errors.',
        rich_help_panel='Behavior',
    ),
]






@dc.dataclass(slots=True)
class TLSComponents:
    def cert_table(self, result: TLSCertificateResult) -> Table:
        title = f'TLS Certificate \u2014 {result.hostname}:{result.port}'
        table = cli_utils.keyvalue_table(title)

        valid_from = (
            result.valid_from.strftime('%Y-%m-%d %H:%M UTC')
            if result.valid_from
            else None
        )
        valid_until = (
            result.valid_until.strftime('%Y-%m-%d %H:%M UTC')
            if result.valid_until
            else None
        )

        fields: dict[str, object] = {
            'Hostname': result.hostname,
            'Port': result.port,
            'Issued To': result.issued_to,
            'Issued By': result.issued_by,
            'Valid From': valid_from,
            'Valid Until': valid_until,
            'Serial Number': result.serial_number,
            'Version': result.version,
        }
        for label, value in fields.items():
            cli_utils.tablerow(table, label, value)

        return table

    def san_table(self, result: TLSCertificateResult) -> Table:
        table = Table(
            title='Subject Alternative Names',
            box=MINIMAL_DOUBLE_HEAD,
            show_header=False,
        )
        table.add_column('DNS Name', overflow='fold')

        if not result.subject_alternative_names:
            table.add_row('[dim]None[/dim]')
        else:
            for san in result.subject_alternative_names:
                table.add_row(san)

        return table

    def cert_group(self, result: TLSCertificateResult) -> Group:
        return Group(self.cert_table(result), self.san_table(result))

    def batch_overview_table(self, batch: TLSBatchResult) -> Table:
        table = Table(
            title=f'TLS Batch \u2014 {batch.total} host(s)',
            box=MINIMAL_DOUBLE_HEAD,
        )
        table.add_column('Hostname', overflow='fold')
        table.add_column('Port', justify='right', no_wrap=True)
        table.add_column('Issued To', overflow='fold')
        table.add_column('Issued By', overflow='fold')
        table.add_column('Valid Until', no_wrap=True)
        table.add_column('Status', no_wrap=True)

        for result in batch.succeeded:
            valid_until = (
                result.valid_until.strftime('%Y-%m-%d') if result.valid_until else '-'
            )
            table.add_row(
                result.hostname,
                str(result.port),
                result.issued_to or '[dim]-[/dim]',
                result.issued_by or '[dim]-[/dim]',
                valid_until,
                '[green]OK[/green]',
            )

        for hostname, error in batch.failed.items():
            table.add_row(
                hostname,
                '',
                '',
                '',
                '',
                f'[red]ERROR[/red] {error}',
            )

        return table




@dc.dataclass(slots=True)
class TLSConsole:
    console: Console = dc.field(default_factory=Console)
    components: TLSComponents = dc.field(default_factory=TLSComponents)

    def render_single(self, result: TLSCertificateResult) -> None:
        self.console.print(self.components.cert_group(result))

    def render_batch(self, batch: TLSBatchResult) -> None:
        renderables = [self.components.batch_overview_table(batch)]

        if batch.failed:
            renderables.append(cli_utils.error_table(batch.failed, title='Failed Hosts'))

        self.console.print(Group(*renderables))

    def render_no_hosts_error(self) -> None:
        self.console.print(
            Panel(
                Text.from_markup(
                    '[bold red]No hosts provided.[/] Use [bold]--host[/] at least once.'
                ),
                title='Error',
                border_style='red',
            )
        )




def _build_options(port: int, timeout: float, verify: bool) -> TLSClientOptions:  # noqa: FBT001
    return TLSClientOptions(port=port, timeout=timeout, verify=verify)


async def run_tls_check(
    hostname: str,
    port: int,
    timeout: float,  # noqa: ASYNC109
    verify: bool,  # noqa: FBT001
) -> int:
    tls = TLSConsole()
    options = _build_options(port, timeout, verify)
    integration = TLSIntegration(options=options)
    result = await integration.fetch(hostname)
    tls.render_single(result)
    return 0


async def run_tls_batch(
    hosts: list[str],
    port: int,
    timeout: float,  # noqa: ASYNC109
    verify: bool,  # noqa: FBT001
    concurrency_limit: int | None,
    fail_fast: bool,  # noqa: FBT001
) -> int:
    tls = TLSConsole()
    options = _build_options(port, timeout, verify)
    integration = TLSIntegration(options=options)
    batch = await integration.fetch_many(
        hosts,
        concurrency_limit=concurrency_limit,
        fail_fast=fail_fast,
    )
    tls.render_batch(batch)
    return 0 if batch.okay else 1



@tls_app.command('check')
def tls_check_command(
    host: HostArgument,
    *,
    port: PortOption = 443,
    timeout: TimeoutOption = 10.0,
    verify: VerifyOption = True,
) -> None:
    with cli_utils.cli_exception_guard('TLS certificate check failed'):
        exit_code = anyio.run(run_tls_check, host, port, timeout, verify)

    raise typer.Exit(code=exit_code)


@tls_app.command('batch')
def tls_batch_command(
    *,
    hosts: HostsOption,
    port: PortOption = 443,
    timeout: TimeoutOption = 10.0,
    verify: VerifyOption = True,
    concurrency: ConcurrencyOption = None,
    fail_fast: FailFastOption = False,
) -> None:
    """Fetch TLS certificates for multiple hosts concurrently."""
    tls_console = TLSConsole()

    if not hosts:
        tls_console.render_no_hosts_error()
        raise typer.Exit(code=1)

    with cli_utils.cli_exception_guard('TLS batch check failed'):
        exit_code = anyio.run(
            run_tls_batch,
            hosts,
            port,
            timeout,
            verify,
            concurrency,
            fail_fast,
        )

    raise typer.Exit(code=exit_code)
