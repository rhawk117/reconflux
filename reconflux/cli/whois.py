from __future__ import annotations

import dataclasses as dc
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any

import anyio
import typer
from rich.box import MINIMAL_DOUBLE_HEAD
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from reconflux.cli import utils as cli_utils
from reconflux.integrations.rdap import RDAPProvider
from reconflux.net.http import HttpPerformancePreset

if TYPE_CHECKING:
    from reconflux.net.rdap import (
        RDAPAutnumRecord,
        RDAPContact,
        RDAPDomainRecord,
        RDAPLookupResult,
        RDAPNetworkRecord,
    )

"""
uv run reconflux whois domain github.com
uv run reconflux whois domain google.com
uv run reconflux whois ip 8.8.8.8
uv run reconflux whois asn 15169   # Google's ASN
uv run reconflux whois asn 13335   # Cloudflare's ASN

"""


whois_app = typer.Typer()


DomainArgument = Annotated[
    str,
    typer.Argument(help='Domain name to query.', metavar='DOMAIN'),
]

IPArgument = Annotated[
    str,
    typer.Argument(help='IP address to query.', metavar='IP'),
]

ASNArgument = Annotated[
    int,
    typer.Argument(help='Autonomous system number to query.', metavar='ASN'),
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

MaxReferralsOption = Annotated[
    int,
    typer.Option(
        '--max-referrals',
        min=1,
        max=20,
        help='Maximum RDAP referral hops before giving up.',
        rich_help_panel='HTTP',
        show_default=True,
    ),
]


_DT_FMT = '%Y-%m-%d %H:%M UTC'


def _fmt_dt(dt: datetime | None) -> str | None:
    return dt.strftime(_DT_FMT) if dt is not None else None


def _contact_panel(contact: RDAPContact, label: str) -> Panel:
    table = cli_utils.keyvalue_table(label)
    fields: list[tuple[str, Any]] = [
        ('Roles', ', '.join(contact.roles) if contact.roles else None),
        ('Full Name', contact.full_name),
        ('Organization', contact.organization),
        ('Email', contact.email),
        ('Phone', contact.phone),
        ('Fax', contact.fax),
        ('Address', contact.address),
        ('Contact URI', contact.contact_uri),
        ('Country', contact.country),
        ('Handle', contact.handle),
    ]
    for field, value in fields:
        cli_utils.tablerow(table, field, value)
    return Panel(table, border_style='dim')


def _contacts_group(
    contacts: list[tuple[str, RDAPContact | None]],
) -> Group:
    panels = []
    for label, contact in contacts:
        if contact is not None:
            panels.append(_contact_panel(contact, label))
    if not panels:
        panels.append(Text('[dim]No contact information available.[/dim]'))
    return Group(*panels)


@dc.dataclass(slots=True)
class WhoisComponents:
    def _resolved_url_note(self, resolved_url: str) -> Text:
        return Text.from_markup(f'[dim]Resolved via:[/dim] {resolved_url}')

    def domain_group(
        self,
        result: RDAPLookupResult[RDAPDomainRecord, Any],
    ) -> Group:
        rec = result.record
        summary = cli_utils.keyvalue_table(f'Domain  \u2014  {rec.query}')
        fields: list[tuple[str, Any]] = [
            ('Handle', rec.handle),
            ('LDH Name', rec.ldh_name),
            ('Unicode Name', rec.unicode_name),
            ('Status', ', '.join(rec.statuses) if rec.statuses else None),
            ('Created', _fmt_dt(rec.created_at)),
            ('Updated', _fmt_dt(rec.updated_at)),
            ('Expires', _fmt_dt(rec.expires_at)),
            ('Last Changed', _fmt_dt(rec.last_changed_at)),
            ('Entities', rec.raw_entities_count),
        ]
        for label, value in fields:
            cli_utils.tablerow(summary, label, value)

        ns_table = Table(
            title='Nameservers',
            box=MINIMAL_DOUBLE_HEAD,
            show_header=False,
        )
        ns_table.add_column('Nameserver', overflow='fold')
        if rec.nameservers:
            for ns in rec.nameservers:
                ns_table.add_row(ns)
        else:
            ns_table.add_row('[dim]None[/dim]')

        contacts = _contacts_group([
            ('Registrant', rec.registrant),
            ('Registrar', rec.registrar),
            ('Administrative', rec.administrative),
            ('Technical', rec.technical),
            ('Abuse', rec.abuse),
            ('Billing', rec.billing),
        ])

        return Group(
            summary,
            ns_table,
            contacts,
            self._resolved_url_note(result.resolved_url),
        )

    def network_group(
        self,
        result: RDAPLookupResult[RDAPNetworkRecord, Any],
    ) -> Group:
        rec = result.record
        summary = cli_utils.keyvalue_table(
            f'IP Network  \u2014  {rec.query}  ({rec.ip_version or "?"})'
        )
        fields: list[tuple[str, Any]] = [
            ('Handle', rec.handle),
            ('Start Address', rec.start_address),
            ('End Address', rec.end_address),
            ('IP Version', rec.ip_version),
            ('Network Name', rec.network_name),
            ('Network Type', rec.network_type),
            ('Country', rec.country),
            ('Status', ', '.join(rec.statuses) if rec.statuses else None),
            ('Created', _fmt_dt(rec.created_at)),
            ('Updated', _fmt_dt(rec.updated_at)),
            ('Last Changed', _fmt_dt(rec.last_changed_at)),
            ('Entities', rec.raw_entities_count),
        ]
        for label, value in fields:
            cli_utils.tablerow(summary, label, value)

        contacts = _contacts_group([
            ('Abuse', rec.abuse),
            ('Technical', rec.technical),
            ('Administrative', rec.administrative),
        ])

        return Group(
            summary,
            contacts,
            self._resolved_url_note(result.resolved_url),
        )

    def autnum_group(
        self,
        result: RDAPLookupResult[RDAPAutnumRecord, Any],
    ) -> Group:
        rec = result.record
        summary = cli_utils.keyvalue_table(f'ASN  \u2014  {rec.query}')
        fields: list[tuple[str, Any]] = [
            ('Handle', rec.handle),
            ('Name', rec.name),
            ('Type', rec.autnum_type),
            ('Country', rec.country),
            ('Start Autnum', rec.start_autnum),
            ('End Autnum', rec.end_autnum),
            ('Status', ', '.join(rec.statuses) if rec.statuses else None),
            ('Created', _fmt_dt(rec.created_at)),
            ('Updated', _fmt_dt(rec.updated_at)),
            ('Last Changed', _fmt_dt(rec.last_changed_at)),
            ('Entities', rec.raw_entities_count),
        ]
        for label, value in fields:
            cli_utils.tablerow(summary, label, value)

        contacts = _contacts_group([
            ('Abuse', rec.abuse),
            ('Technical', rec.technical),
            ('Administrative', rec.administrative),
        ])

        return Group(
            summary,
            contacts,
            self._resolved_url_note(result.resolved_url),
        )


@dc.dataclass(slots=True)
class WhoisConsole:
    console: Console = dc.field(default_factory=Console)
    components: WhoisComponents = dc.field(default_factory=WhoisComponents)

    def render_domain(self, result: RDAPLookupResult[RDAPDomainRecord, Any]) -> None:
        self.console.print(self.components.domain_group(result))

    def render_network(self, result: RDAPLookupResult[RDAPNetworkRecord, Any]) -> None:
        self.console.print(self.components.network_group(result))

    def render_autnum(self, result: RDAPLookupResult[RDAPAutnumRecord, Any]) -> None:
        self.console.print(self.components.autnum_group(result))


async def _fetch_domain(
    domain: str,
    optimization: HttpPerformancePreset,
    max_referrals: int,
) -> RDAPLookupResult[RDAPDomainRecord, Any]:
    async with RDAPProvider(
        performance=optimization,
        max_referral_depth=max_referrals,
    ) as provider:
        return await provider.fetch_domain(domain)


async def _fetch_ip(
    address: str,
    optimization: HttpPerformancePreset,
    max_referrals: int,
) -> RDAPLookupResult[RDAPNetworkRecord, Any]:
    async with RDAPProvider(
        performance=optimization,
        max_referral_depth=max_referrals,
    ) as provider:
        return await provider.fetch_ip(address)


async def _fetch_asn(
    asn: int,
    optimization: HttpPerformancePreset,
    max_referrals: int,
) -> RDAPLookupResult[RDAPAutnumRecord, Any]:
    async with RDAPProvider(
        performance=optimization,
        max_referral_depth=max_referrals,
    ) as provider:
        return await provider.fetch_asn(asn)


@whois_app.command('domain')
def whois_domain_command(
    domain: DomainArgument,
    *,
    optimization: OptimizationOption = 'low_latency',
    max_referrals: MaxReferralsOption = 6,
) -> None:
    """RDAP registration lookup for a domain name."""
    wc = WhoisConsole()
    with cli_utils.cli_exception_guard('RDAP domain lookup failed'):
        result = anyio.run(_fetch_domain, domain, optimization, max_referrals)
        wc.render_domain(result)

    raise typer.Exit(code=0)


@whois_app.command('ip')
def whois_ip_command(
    address: IPArgument,
    *,
    optimization: OptimizationOption = 'low_latency',
    max_referrals: MaxReferralsOption = 6,
) -> None:
    """RDAP network block lookup for an IP address."""
    wc = WhoisConsole()
    with cli_utils.cli_exception_guard('RDAP IP lookup failed'):
        result = anyio.run(_fetch_ip, address, optimization, max_referrals)
        wc.render_network(result)

    raise typer.Exit(code=0)


@whois_app.command('asn')
def whois_asn_command(
    asn: ASNArgument,
    *,
    optimization: OptimizationOption = 'low_latency',
    max_referrals: MaxReferralsOption = 6,
) -> None:
    """RDAP autonomous system lookup for an ASN."""
    wc = WhoisConsole()
    with cli_utils.cli_exception_guard('RDAP ASN lookup failed'):
        result = anyio.run(_fetch_asn, asn, optimization, max_referrals)
        wc.render_autnum(result)

    raise typer.Exit(code=0)
