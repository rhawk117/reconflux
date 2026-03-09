import contextlib
from typing import TYPE_CHECKING

import typer
from rich.box import MINIMAL_DOUBLE_HEAD
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from collections.abc import Generator

console = Console()

@contextlib.contextmanager
def cli_exception_guard(error_message: str) -> Generator[None]:
    try:
        yield
    except KeyboardInterrupt as exc:
        raise typer.Exit(code=130) from exc
    except Exception as exc:
        error_panel = Panel(
            Text.from_markup(f'[bold red]{error_message}[/] {exc!r}'),
            title='Unhandled Error',
            border_style='red',
        )
        console.print(error_panel)
        raise typer.Exit(code=1) from exc

def error_table(errors: dict[str, str], *, title: str) -> Table:
    table = Table(title=title, box=MINIMAL_DOUBLE_HEAD)
    table.add_column('Task')
    table.add_column('Error', overflow='fold')

    if not errors:
        table.add_row('None', '')
        return table

    for task_name, error_text in errors.items():
        table.add_row(task_name, error_text)

    return table

def keyvalue_table(title: str) -> Table:
    table = Table(title=title, box=MINIMAL_DOUBLE_HEAD, show_header=False)
    table.add_column('Field', no_wrap=True, style='bold')
    table.add_column('Value', overflow='fold')
    return table


def tablerow(table: Table, label: str, value: object) -> None:
    table.add_row(label, str(value) if value is not None else '[dim]-[/dim]')
