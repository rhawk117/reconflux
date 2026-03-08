from __future__ import annotations

import contextlib
import socket
import ssl
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from reconflux.core import ReconfluxError
from reconflux.net.tls._models import TLSCertificateResult, TLSClientOptions

if TYPE_CHECKING:
    from collections.abc import Generator

_TLS_DATETIME_FORMAT = '%b %d %H:%M:%S %Y %Z'


class TLSCertificateError(ReconfluxError):
    default_message = 'Failed to retrieve TLS certificate.'
    error_code = 'tls_certificate_error'


def name_entries_to_dict(name: object) -> dict[str, str]:
    if not isinstance(name, tuple):
        return {}

    flattened: dict[str, str] = {}
    for rdn in name:
        if not isinstance(rdn, tuple):
            continue

        for pair in rdn:
            if not isinstance(pair, tuple) or len(pair) != 2:
                continue

            key, value = pair
            if isinstance(key, str) and isinstance(value, str):
                flattened[key] = value

    return flattened


def parse_certificate_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None

    try:
        dt = datetime.strptime(value, _TLS_DATETIME_FORMAT)  # noqa: DTZ007
        return dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def extract_subject_alternative_names(certificate: object) -> list[str]:
    if not isinstance(certificate, dict):
        return []

    san_entries = certificate.get('subjectAltName', [])
    hostnames: list[str] = []

    if not isinstance(san_entries, list | tuple):
        return hostnames

    for entry in san_entries:
        if not isinstance(entry, tuple) or len(entry) != 2:
            continue

        entry_type, entry_value = entry
        if entry_type == 'DNS':
            hostnames.append(str(entry_value))

    return hostnames


def make_ssl_context(*, verify: bool) -> ssl.SSLContext:
    if verify:
        return ssl.create_default_context()

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context


@contextlib.contextmanager
def propogate_tls_errors(
    options: TLSClientOptions,
    hostname: str,
) -> Generator[None]:
    try:
        yield
    except ssl.SSLError as exc:
        raise TLSCertificateError(
            (f'An SSL error occurred while retrieving the certificate for {hostname!r}.'),
            context={
                'hostname': hostname,
                'port': options.port,
            },
        ) from exc
    except TimeoutError as exc:
        raise TLSCertificateError(
            f'The connection timed out while retrieving the certificate for {hostname!r}',
            context={
                'hostname': hostname,
                'port': options.port,
                'timeout': options.timeout,
            },
        ) from exc
    except OSError as exc:
        raise TLSCertificateError(
            f'Failed to connect to {hostname!r} for TLS certificate retrieval.',
            context={
                'hostname': hostname,
                'port': options.port,
            },
        ) from exc


def fetch_tls_certificate_sync(
    hostname: str,
    options: TLSClientOptions | None = None,
) -> TLSCertificateResult:
    resolved_options = options or TLSClientOptions()
    ssl_context = make_ssl_context(verify=resolved_options.verify)

    socket_opts = (hostname, resolved_options.port)
    with (
        propogate_tls_errors(resolved_options, hostname),
        socket.create_connection(socket_opts, timeout=resolved_options.timeout) as sock,
        ssl_context.wrap_socket(sock, server_hostname=hostname) as tls_socket,
    ):
        raw_certificate = tls_socket.getpeercert()

    certificate = raw_certificate if isinstance(raw_certificate, dict) else {}

    subject = name_entries_to_dict(certificate.get('subject'))
    issuer = name_entries_to_dict(certificate.get('issuer'))

    issued_to = subject.get('commonName')
    issued_by = issuer.get('commonName')
    valid_from = parse_certificate_datetime(certificate.get('notBefore'))
    valid_until = parse_certificate_datetime(certificate.get('notAfter'))

    raw_serial_number = certificate.get('serialNumber')
    serial_number = raw_serial_number if isinstance(raw_serial_number, str) else None

    raw_version = certificate.get('version')
    version = raw_version if isinstance(raw_version, int) else None

    subject_alternative_names = extract_subject_alternative_names(certificate)

    return TLSCertificateResult(
        hostname=hostname,
        port=resolved_options.port,
        issued_to=issued_to,
        issued_by=issued_by,
        valid_from=valid_from,
        valid_until=valid_until,
        serial_number=serial_number,
        version=version,
        subject_alternative_names=subject_alternative_names,
        raw_certificate=certificate,
    )


