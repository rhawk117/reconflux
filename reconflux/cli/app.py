import anyio
import typer

from reconflux.app.logging import LoggingExtension


async def setup_logging() -> None:
    logging_extension = await LoggingExtension.resolve()
    logging_extension.configure_loggers()

def create_cli_app() -> typer.Typer:
    from reconflux.cli.dns import dns_app
    from reconflux.cli.net import net_app

    app = typer.Typer(
        name='reconflux',
        no_args_is_help=True,
        rich_markup_mode='rich',
        help='Reconflux terminal interface.',
    )

    app.add_typer(
        dns_app,
        name='dns',
        no_args_is_help=True,
        help='Run DNS reconnaissance workflows.',
    )

    app.add_typer(
        net_app,
        name='providers',
        no_args_is_help=True,
        help='Query third-party data providers (cert.sh, ipinfo.io).',
    )

    return app


def run() -> None:
    anyio.run(setup_logging)
    app = create_cli_app()
    app()


if __name__ == '__main__':
    run()
