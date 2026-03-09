from __future__ import annotations

import dataclasses as dc
import json
from typing import TYPE_CHECKING, Annotated, Any

import anyio
import typer
from rich.box import MINIMAL_DOUBLE_HEAD
from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from reconflux.cli import utils as cli_utils
from reconflux.integrations.web_scraper import (
    BatchWebScrapeResult,
    WebScrapeResult,
    WebScraperIntegration,
)
from reconflux.net.http import HttpPerformancePreset

if TYPE_CHECKING:
    from reconflux.web_scrapers import (
        HydrationScrapperResults,
        ScriptTagData,
        WebsiteHeadData,
    )

"""test commands
# Single page deep scrape — see all hydration blobs, window vars, scripts
  uv run reconflux web scrape https://ifunny.co

  # A specific meme/post page (likely has heavier hydration payload)
  uv run reconflux web scrape https://ifunny.co/picture/some-post-id

  # Batch across several sections at once
  uv run reconflux web batch \
    --url https://ifunny.co \
    --url https://ifunny.co/trending \
    --url https://ifunny.co/collective \
    --url https://ifunny.co/tags/memes

  # Batch with concurrency cap (polite)
  uv run reconflux web batch \
    --url https://ifunny.co \
    --url https://ifunny.co/trending \
    --url https://ifunny.co/collective \
    --concurrency 2

  # High-throughput preset if you want faster fetches on many pages
  uv run reconflux web batch \
    --url https://ifunny.co \
    --url https://ifunny.co/trending \
    --optimization high_throughput

"""

web_app = typer.Typer()


URLArgument = Annotated[
    str,
    typer.Argument(
        help='URL to fetch and analyse.',
        metavar='URL',
    ),
]

URLsOption = Annotated[
    list[str],
    typer.Option(
        '--url',
        '-u',
        help='URL to scrape. Repeat to provide multiple targets.',
        rich_help_panel='Targets',
    ),
]

OptimizationOption = Annotated[
    HttpPerformancePreset,
    typer.Option(
        '--optimization',
        help='HTTP client performance preset.',
        rich_help_panel='HTTP',
        show_default=True,
    ),
]

ConcurrencyOption = Annotated[
    int | None,
    typer.Option(
        '--concurrency',
        '-c',
        min=1,
        help='Maximum simultaneous fetches. Omit for no cap.',
        rich_help_panel='Behavior',
    ),
]

BatchTimeoutOption = Annotated[
    float | None,
    typer.Option(
        '--timeout',
        min=0.1,
        help='Wall-clock timeout in seconds for the entire batch.',
        rich_help_panel='Behavior',
    ),
]

FailFastOption = Annotated[
    bool,
    typer.Option(
        '--fail-fast/--collect-errors',
        help='Abort on the first scrape failure or collect per-URL errors.',
        rich_help_panel='Behavior',
    ),
]

PprintOption = Annotated[
    bool,
    typer.Option(
        '--pprint',
        help=(
            'Pretty-print full hydration blobs (window variables and selector matches)'
            'as syntax-highlighted JSON.'
        ),
        rich_help_panel='Output',
        is_flag=True,
    ),
]


def _list_table(title: str, column: str, items: list[str]) -> Table:
    table = Table(title=title, box=MINIMAL_DOUBLE_HEAD, show_header=False)
    table.add_column(column, overflow='fold')
    if items:
        for item in items:
            table.add_row(item)
    else:
        table.add_row('[dim]None[/dim]')
    return table


def _kv_pairs_table(title: str, data: dict[str, str]) -> Table:
    table = cli_utils.keyvalue_table(title)
    if data:
        for key, value in data.items():
            cli_utils.tablerow(table, key, value)
    else:
        table.add_row('[dim]None[/dim]', '')
    return table


@dc.dataclass(slots=True)
class WebComponents:  # lol no those kinds
    def summary_panel(self, result: WebScrapeResult) -> Panel:
        common = result.head.common
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style='bold', no_wrap=True)
        grid.add_column(overflow='fold')

        rows: list[tuple[str, object]] = [
            ('URL', result.url),
            ('Status', str(result.status_code)),
            ('Description', common.description),
            ('Keywords', common.keywords),
            ('Charset', common.charset),
            ('Robots', common.robots),
            ('Anchors', str(len(result.anchors))),
            ('Scripts', str(len(result.scripts))),
            ('Data URLs', str(len(result.data_urls))),
        ]
        for label, value in rows:
            grid.add_row(label, str(value) if value is not None else '[dim]-[/dim]')

        return Panel(grid, title='Web Scrape Summary', border_style='cyan')

    def head_table(self, head: WebsiteHeadData) -> Group:
        og = _kv_pairs_table('Open Graph', head.categories.open_graph)
        security = _kv_pairs_table('Security Meta Tags', head.categories.security)
        extras = _kv_pairs_table('Extra Meta Tags', head.categories.extras)
        return Group(og, security, extras)

    def packages_table(self, head: WebsiteHeadData) -> Group:
        js = _list_table('JavaScript', 'URL', head.packages.javascript)
        css = _list_table('CSS', 'URL', head.packages.css)
        cdn = _list_table('CDN Resources', 'URL', head.packages.cdn_like)
        return Group(js, css, cdn)

    def scripts_table(self, scripts: list[ScriptTagData]) -> Table:
        table = Table(title='Script Tags', box=MINIMAL_DOUBLE_HEAD)
        table.add_column('Src', overflow='fold')
        table.add_column('Type', no_wrap=True)
        table.add_column('Preview', overflow='fold')
        table.add_column('JSON Keys', overflow='fold')
        table.add_column('Fetched URLs', overflow='fold')

        non_empty = [s for s in scripts if not s.is_empty()]
        if not non_empty:
            table.add_row('[dim]None[/dim]', '', '', '', '')
            return table

        for script in non_empty:
            json_keys = ''
            if script.json_data and script.json_data.data_keys:
                json_keys = ', '.join(sorted(script.json_data.data_keys)[:8])
                if len(script.json_data.data_keys) > 8:
                    json_keys += f' (+{len(script.json_data.data_keys) - 8} more)'

            fetched_urls = ''
            if script.inline_data and script.inline_data.fetched_urls:
                all_urls: list[str] = [
                    f'[{label}] {url}'
                    for label, urls in script.inline_data.fetched_urls.items()
                    for url in urls
                ]
                fetched_urls = '\n'.join(all_urls[:5])
                if len(all_urls) > 5:
                    fetched_urls += f'\n(+{len(all_urls) - 5} more)'

            table.add_row(
                script.src or '[dim]-[/dim]',
                script.tag_type or '[dim]-[/dim]',
                script.get_content_preview(80),
                json_keys or '[dim]-[/dim]',
                fetched_urls or '[dim]-[/dim]',
            )

        return table

    def hydration_table(self, hydration: HydrationScrapperResults) -> Group:
        sel_table = Table(title='Selector Hydration', box=MINIMAL_DOUBLE_HEAD)
        sel_table.add_column('Selector', no_wrap=True)
        sel_table.add_column('Keys', overflow='fold')

        non_empty_selectors = {k: v for k, v in hydration.selector_matches.items() if v}
        if non_empty_selectors:
            for selector, blob in non_empty_selectors.items():
                if isinstance(blob, dict):
                    keys = ', '.join(list(blob.keys())[:10])
                elif isinstance(blob, list):
                    keys = f'[list of {len(blob)}]'
                else:
                    keys = str(blob)
                sel_table.add_row(selector, keys)
        else:
            sel_table.add_row('[dim]None[/dim]', '')

        win_table = Table(title='Window Variables', box=MINIMAL_DOUBLE_HEAD)
        win_table.add_column('Variable', no_wrap=True)
        win_table.add_column('Type', no_wrap=True)
        win_table.add_column('Keys', overflow='fold')

        if hydration.window_variables:
            for var in hydration.window_variables:
                if isinstance(var.blob, dict):
                    keys = ', '.join(list(var.blob.keys())[:8])
                elif isinstance(var.blob, list):
                    keys = f'[list of {len(var.blob)}]'
                else:
                    keys = str(var.blob)
                win_table.add_row(var.variable_name, var.label, keys)
        else:
            win_table.add_row('[dim]None[/dim]', '', '')

        return Group(sel_table, win_table)

    def _blob_panel(self, title: str, blob: Any) -> Panel:
        try:
            text = json.dumps(blob, indent=2, default=str)
        except TypeError, ValueError:
            text = str(blob)
        return Panel(
            Syntax(text, 'json', theme='monokai', word_wrap=True),
            title=title,
            border_style='yellow',
        )

    def hydration_pprint(self, hydration: HydrationScrapperResults) -> Group:
        renderables: list[object] = []

        non_empty_selectors = {k: v for k, v in hydration.selector_matches.items() if v}
        if non_empty_selectors:
            for selector, blob in non_empty_selectors.items():
                renderables.append(self._blob_panel(f'Selector: {selector}', blob))
        else:
            renderables.append(
                Panel(Text('[dim]No selector hydration found.[/dim]'), border_style='dim')
            )

        if hydration.window_variables:
            for var in hydration.window_variables:
                label = f'[{var.label}] {var.variable_name}'
                renderables.append(self._blob_panel(label, var.blob))
        else:
            renderables.append(
                Panel(Text('[dim]No window variables found.[/dim]'), border_style='dim')
            )

        return Group(*renderables)

    def anchors_table(self, anchors: list[str]) -> Table:
        return _list_table(f'Anchors ({len(anchors)})', 'href', anchors)

    def data_urls_table(self, data_urls: list[str]) -> Table:
        return _list_table(f'Data URLs ({len(data_urls)})', 'URL', data_urls)

    def batch_summary_table(self, batch: BatchWebScrapeResult) -> Table:
        table = Table(
            title=f'Web Scrape Batch \u2014 {batch.total} URL(s)',
            box=MINIMAL_DOUBLE_HEAD,
        )
        table.add_column('URL', overflow='fold')
        table.add_column('Status', justify='right', no_wrap=True)
        table.add_column('Title / Description', overflow='fold')
        table.add_column('Scripts', justify='right', no_wrap=True)
        table.add_column('Anchors', justify='right', no_wrap=True)
        table.add_column('Data URLs', justify='right', no_wrap=True)
        table.add_column('Result', no_wrap=True)

        for result in batch.succeeded:
            description = result.head.common.description or '[dim]-[/dim]'
            table.add_row(
                result.url,
                str(result.status_code),
                description[:60] + ('…' if len(description) > 60 else ''),
                str(len(result.scripts)),
                str(len(result.anchors)),
                str(len(result.data_urls)),
                '[green]OK[/green]',
            )

        for url, error in batch.failed.items():
            table.add_row(
                url,
                '',
                f'[red]{error}[/red]',
                '',
                '',
                '',
                '[red]ERROR[/red]',
            )

        return table


@dc.dataclass(slots=True)
class WebConsole:
    console: Console = dc.field(default_factory=Console)
    components: WebComponents = dc.field(default_factory=WebComponents)

    def render_scrape(self, result: WebScrapeResult, *, pprint: bool = False) -> None:
        hydration_renderable = (
            self.components.hydration_pprint(result.hydration)
            if pprint
            else self.components.hydration_table(result.hydration)
        )
        renderables = [
            self.components.summary_panel(result),
            self.components.head_table(result.head),
            self.components.packages_table(result.head),
            self.components.scripts_table(result.scripts),
            hydration_renderable,
        ]
        if result.data_urls:
            renderables.append(self.components.data_urls_table(result.data_urls))
        if result.anchors:
            renderables.append(self.components.anchors_table(result.anchors))

        self.console.print(Group(*renderables))

    def render_batch(self, batch: BatchWebScrapeResult) -> None:
        renderables = [self.components.batch_summary_table(batch)]

        if batch.failed:
            renderables.append(cli_utils.error_table(batch.failed, title='Failed URLs'))

        self.console.print(Group(*renderables))

    def render_no_urls_error(self) -> None:
        self.console.print(
            Panel(
                Text.from_markup(
                    '[bold red]No URLs provided.[/] Use [bold]--url[/] at least once.'
                ),
                title='Error',
                border_style='red',
            )
        )


async def run_web_scrape(
    url: str,
    optimization: HttpPerformancePreset,
    pprint: bool,  # noqa: FBT001
) -> int:
    web = WebConsole()
    async with WebScraperIntegration(performance=optimization) as integration:
        result = await integration.scrape(url)

    web.render_scrape(result, pprint=pprint)
    return 0


async def run_web_batch(
    urls: list[str],
    optimization: HttpPerformancePreset,
    concurrency_limit: int | None,
    batch_timeout: float | None,
    fail_fast: bool,  # noqa: FBT001
) -> int:
    web = WebConsole()
    async with WebScraperIntegration(performance=optimization) as integration:
        batch = await integration.scrape_many(
            urls,
            concurrency_limit=concurrency_limit,
            timeout=batch_timeout,
            fail_fast=fail_fast,
        )

    web.render_batch(batch)
    return 0 if batch.okay else 1


@web_app.command('scrape')
def web_scrape_command(
    url: URLArgument,
    *,
    optimization: OptimizationOption = 'scraping',
    pprint: PprintOption = False,
) -> None:
    """Fetch and analyse a single URL: head tags, scripts, hydration blobs, anchors."""
    with cli_utils.cli_exception_guard('Web scrape failed'):
        exit_code = anyio.run(run_web_scrape, url, optimization, pprint)

    raise typer.Exit(code=exit_code)


@web_app.command('batch')
def web_batch_command(
    *,
    urls: URLsOption,
    optimization: OptimizationOption = 'scraping',
    concurrency: ConcurrencyOption = None,
    timeout: BatchTimeoutOption = None,
    fail_fast: FailFastOption = False,
) -> None:
    """Scrape multiple URLs concurrently and display a summary table."""
    web_console = WebConsole()

    if not urls:
        web_console.render_no_urls_error()
        raise typer.Exit(code=1)

    with cli_utils.cli_exception_guard('Web batch scrape failed'):
        exit_code = anyio.run(
            run_web_batch,
            urls,
            optimization,
            concurrency,
            timeout,
            fail_fast,
        )

    raise typer.Exit(code=exit_code)
