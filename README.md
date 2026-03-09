# reconflux

> **Early development.** APIs are unstable. Expect breaking changes between commits.

A modern, async-first Python OSINT framework and CLI. Spiritual successor to reconoscope.

Reconflux is designed to work both ways — as a **CLI tool** you run directly from the terminal, and as a **library** you import and compose in your own scripts, pipelines, or tooling. Every integration is a plain async class with no hidden state; the CLI is just a thin rendering layer on top of the same objects you use in code.

Built on Python 3.14+ with `anyio`, `httpx`, `dnspython`, `pydantic`, and `rich` at the core.

---

## Getting Started

```bash
git clone https://github.com/your-org/reconflux
cd reconflux
uv sync
uv run reconflux
```

`uv sync` installs all dependencies and registers the `reconflux` CLI entry point. After that, every command below is available as `uv run reconflux <command>`.

---

## Architecture

Reconflux is organized into strict layers. Nothing in the lower layers imports from the layers above it.

```
reconflux/
├── net/            # Low-level async clients — DNS, HTTP, TLS, RDAP
├── integrations/   # High-level OSINT workflows built on net/
├── web_scrapers/   # HTML/JS parsing utilities used by the web integration
├── files/          # File analysis — PDF, DOCX, XLSX, PPTX, images, audio
├── concurrency.py  # Task execution primitives (anyio-backed)
├── core/           # Base models, errors, warnings, settings
├── app/            # Logging config, appdata path resolution
└── cli/            # Typer commands — renders integration output with Rich
```

**Dependency direction:** `cli → integrations → net → core`

All integration result types are `@dataclass(slots=True)` with a `DataclassMixin` that adds `.asdict()`, `.astuple()`, `.replace()`, and `.fields()`. Pydantic models (settings, request validation) extend `ReconfluxModel` which enforces `extra='forbid'`, `str_strip_whitespace=True`, and `validate_assignment=True`.

---

## Integrations

### DNS

Full concurrent domain record enumeration, reverse PTR lookups, email DNS analysis (MX/SPF/DMARC), and DNSBL blocklist checking. All queries for a given target run concurrently via the `run_concurrently` task executor.

```python
import anyio
from reconflux.integrations.dns import DNSProvider, DNSLookupRequest

async def main():
    provider = DNSProvider()

    # Full domain sweep — A, AAAA, CNAME, MX, NS, TXT, SOA, SRV, CAA, PTR
    result = await provider.lookup_domain('github.com')
    a_records = result.queries.results.get('A')
    print(a_records.records)

    # Email DNS — MX, SPF (TXT), and DMARC concurrently
    email = await provider.lookup_email('user@gmail.com')
    print(email.queries.results.get('MX').records)

    # Reverse PTR + DNSBL blocklist check
    reverse = await provider.lookup_ip_address('8.8.8.8')
    print(reverse.reverse_lookup.hostnames)
    print(reverse.blocklists)

    # Unified dispatch — routes domain/IP/email based on what field is set
    request = DNSLookupRequest(domain='example.com')
    result = await provider.dispatch(request)

anyio.run(main)
```

`DNSClientOptions` controls nameservers, EDNS, TCP fallback, timeout, lifetime, and search-domain behavior. Pass it to `DNSProvider(client_options=...)` or construct a `DNSClient` directly and inject it.

---

### RDAP / WHOIS

Bootstrap-based RDAP resolution for domains, IP network blocks, and autonomous system numbers. Follows IANA bootstrap redirects and referral chains to find the authoritative registry, then normalizes the response into structured records with contact extraction from jCard/vcardArray.

```python
import anyio
from reconflux.integrations.rdap import RDAPProvider

async def main():
    async with RDAPProvider() as provider:
        # Domain registration record — handle, nameservers, contacts, timestamps
        domain = await provider.fetch_domain('github.com')
        print(domain.record.registrar.organization)
        print(domain.record.expires_at)
        print(domain.resolved_url)  # which registry answered

        # IP network block — CIDR range, network name, abuse contact
        network = await provider.fetch_ip('8.8.8.8')
        print(network.record.start_address, network.record.end_address)
        print(network.record.abuse.email)

        # Autonomous system record — ASN name, country, type
        asn = await provider.fetch_asn(15169)
        print(asn.record.name, asn.record.country)

anyio.run(main)
```

`max_referral_depth` (default 6) limits how many registry referral hops are followed before giving up. The `performance` parameter accepts any `HttpPerformancePreset` string.

---

### IP Info

Three integration tiers over the ipinfo.io API. The unauthenticated legacy endpoint returns org/ASN data. The lite endpoint returns enriched country metadata. Token-authenticated plans return full geolocation.

```python
import anyio
from reconflux.integrations.ip_info import IPInfoProvider

async def main():
    async with IPInfoProvider() as provider:
        # Unauthenticated — city, country, org (includes "AS15169 Google LLC")
        record = await provider.legacy_search('8.8.8.8')
        print(record.org, record.country, record.timezone)
        print(record.maps_link)  # Google Maps URL from lat/lon

        # Token-authenticated enriched lookup
        # async with IPInfoProvider(token='your_token') as provider:
        #     lite = await provider.lite_search('8.8.8.8')
        #     print(lite.country_name, lite.continent.name, lite.country_flag.emoji)

anyio.run(main)
```

---

### TLS Certificates

Synchronous TLS certificate inspection wrapped for async use via `anyio.to_thread.run_sync`. Supports single-host and concurrent multi-host fetching with per-host error collection.

```python
import anyio
from reconflux.integrations.tls import TLSIntegration
from reconflux.net.tls import TLSClientOptions

async def main():
    tls = TLSIntegration(options=TLSClientOptions(port=443, timeout=10.0))

    # Single host — issuer, subject, SANs, validity window, serial
    cert = await tls.fetch('github.com')
    print(cert.issued_by, cert.valid_until)
    print(cert.subject_alternative_names[:5])

    # Concurrent multi-host with error collection
    batch = await tls.fetch_many(
        ['github.com', 'google.com', 'cloudflare.com'],
        concurrency_limit=3,
        fail_fast=False,
    )
    for hostname, result in batch.results.results.items():
        print(hostname, result.valid_until)
    for hostname, error in batch.failed.items():
        print(f'FAILED {hostname}: {error}')

anyio.run(main)
```

---

### Certificate Transparency (crt.sh)

Subdomain enumeration by querying the crt.sh certificate transparency search API. Deduplicates results across all cert log entries for the domain.

```python
import anyio
from reconflux.integrations.certsh import CertshIntegration

async def main():
    certsh = CertshIntegration()
    result = await certsh.get_subdomains('github.com')
    print(f'Found {result.total} subdomains')
    for sub in result.subdomains[:10]:
        print(sub)

anyio.run(main)
```

---

### Web Scraper

Async HTML fetching with a full scraping pipeline: `<head>` meta-tag analysis, server-side hydration blob extraction (Next.js `__NEXT_DATA__`, custom `window.*` variables), per-`<script>` tag analysis (inline JS patterns, embedded JSON), anchor harvesting, and structured data URL matching. Supports concurrent multi-URL batching.

```python
import anyio
from reconflux.integrations.web_scraper import WebScraperIntegration

async def main():
    async with WebScraperIntegration(performance='scraping') as scraper:
        result = await scraper.scrape('https://example.com')

        # Head meta tags — Open Graph, security headers, charset, robots
        print(result.head.common.description)
        print(result.head.categories.open_graph)
        print(result.head.packages.javascript)  # detected JS bundles

        # Hydration blobs — selector matches and window variable snapshots
        print(result.hydration.window_variables)
        print(result.hydration.selector_matches)

        # Per-script analysis — type, src, inline JSON keys, fetched URLs
        for script in result.scripts:
            if script.json_data:
                print(script.json_data.data_keys)

        # Concurrent batch scrape with optional concurrency cap and timeout
        batch = await scraper.scrape_many(
            ['https://example.com', 'https://example.org'],
            concurrency_limit=5,
            timeout=30.0,
            fail_fast=False,
        )
        for r in batch.succeeded:
            print(r.url, r.status_code, len(r.anchors))

anyio.run(main)
```

The `HydrationScraper`, `ScriptTagScrapper`, and `URLScraper` classes in `reconflux.web_scrapers` are usable standalone if you already have a `BeautifulSoup` object or raw HTML string.

---

### File Analysis

Structured metadata and content extraction across document types. Runs in a thread pool via `anyio` so it fits the async integration model.

```python
import anyio
from reconflux.integrations.files import FileAnalysisIntegration
from pathlib import Path

async def main():
    integration = FileAnalysisIntegration()
    result = await integration.analyze(Path('report.pdf'))
    print(result.metadata)   # author, creation date, page count, etc.
    print(result.text[:500]) # extracted text content

anyio.run(main)
```

Supported formats: PDF, DOCX, XLSX, PPTX, common image formats (EXIF), and audio files (ID3/metadata via `tinytag`).

---

### Phone Numbers

Synchronous phone number validation and enrichment via the `phonenumbers` library. No network call required.

```python
from reconflux.integrations.phone_numbers import PhoneNumberIntegration

integration = PhoneNumberIntegration()
result = integration.lookup('+14155552671')
print(result.country, result.region, result.carrier)
print(result.e164)       # +14155552671
print(result.is_valid)
```

---

## Concurrency Primitives

The `reconflux.concurrency` module provides the task execution infrastructure used by all integrations internally. You can use it directly to build concurrent workflows over any async callable.

```python
import anyio
from reconflux.concurrency import run_concurrently

async def fetch_data(target: str) -> str:
    # your async work here
    return f'result for {target}'

async def main():
    # schedule maps task names to input values
    schedule = {'alpha': 'target-a', 'beta': 'target-b', 'gamma': 'target-c'}

    executor_result = await run_concurrently(
        schedule=schedule,
        runner=fetch_data,
        concurrency_limit=2,   # max 2 tasks in flight at once
        timeout=10.0,          # cancel scope deadline
        fail_fast=False,       # collect errors, don't abort siblings
    )

    print(executor_result.results)  # {'alpha': ..., 'beta': ..., 'gamma': ...}
    print(executor_result.errors)   # per-task error strings for any failures
    print(executor_result.okay)     # True only if no errors

anyio.run(main)
```

For more control, construct a `TaskPlanner` and `TaskExecutor` directly. `TimeSensitiveRunner` wraps any single async operation with `fail_after` or `move_on_after` semantics.

---

## HTTP Client Builder

All HTTP-backed integrations are built on a fluent `ClientOptions` builder. You can use this directly to create `httpx.AsyncClient` instances with consistent performance profiles.

```python
from reconflux.net.http import ClientOptions, new_async_httpx_client

# Fluent builder — returns a new instance at each step (immutable-style)
options = (
    ClientOptions(base_url='https://api.example.com')
    .performance_preset('low_latency')   # timeout/pool tuned for fast queries
    .use_common_headers()                # browser-like Accept, UA, encoding
)

client = new_async_httpx_client(options)
```

Available presets: `default`, `low_latency`, `high_throughput`, `scraping`, `constrained`. Each pre-configures timeouts, connection pool limits, HTTP/2, and redirect behavior for its intended workload.

The `@httpx_retry(attempts=N)` decorator (backed by `tenacity`) applies exponential-backoff retry logic to any async method on an integration.

---

## CLI Reference

All commands are available via `uv run reconflux`. Every subcommand supports `--help`.

### DNS

```bash
# Full domain record sweep — A, AAAA, CNAME, MX, NS, TXT, SOA, CAA
uv run reconflux dns lookup --domain github.com

# Email DNS — MX, SPF, and DMARC
uv run reconflux dns lookup --email user@gmail.com

# Reverse PTR lookup + DNSBL blocklist check
uv run reconflux dns lookup --ip 8.8.8.8

# Custom nameserver and TCP fallback
uv run reconflux dns lookup --domain example.com --nameserver 1.1.1.1 --tcp
```

Queries all record types concurrently. Results render as Rich tables with per-record-type sections and response time.

### WHOIS / RDAP

```bash
# Domain registration — handle, nameservers, registrar/registrant contacts
uv run reconflux whois domain github.com

# IP network block — CIDR range, network name, abuse contact
uv run reconflux whois ip 8.8.8.8

# Autonomous system — name, country, ASN range
uv run reconflux whois asn 15169

# Tune referral depth and HTTP preset
uv run reconflux whois domain github.com --max-referrals 10 --optimization high_throughput
```

### TLS

```bash
# Single certificate — issuer, SANs, validity window
uv run reconflux tls check github.com

# Custom port and timeout
uv run reconflux tls check github.com --port 8443 --timeout 5.0

# Concurrent multi-host batch
uv run reconflux tls batch \
  --host github.com \
  --host google.com \
  --host cloudflare.com \
  --concurrency 5
```

### Web Scraper

```bash
# Single page — head meta tags, hydration blobs, scripts, anchors
uv run reconflux web scrape https://example.com

# Pretty-print hydration blobs as syntax-highlighted JSON in an interactive TUI
uv run reconflux web scrape https://example.com --pprint

# Concurrent batch with interactive result navigator
uv run reconflux web batch \
  --url https://example.com \
  --url https://example.org \
  --concurrency 3

# High-throughput preset for many pages
uv run reconflux web batch \
  --url https://example.com \
  --url https://example.org \
  --optimization high_throughput \
  --timeout 60
```

The `--pprint` flag and batch results open a `prompt_toolkit` full-screen TUI. Navigate with `j`/`k` (or arrow keys), scroll with `Ctrl-D`/`Ctrl-U`, and quit with `q`.

### External (cert.sh, ipinfo.io)

```bash
# Subdomain enumeration via certificate transparency
uv run reconflux external certsh github.com

# IP geolocation — unauthenticated legacy
uv run reconflux external ipinfo 8.8.8.8

# Token-authenticated enriched lookup
uv run reconflux external ipinfo 8.8.8.8 --token YOUR_TOKEN
```

---

## Extending Reconflux

All integration classes are plain async context managers or simple dataclasses — no framework magic. To build your own integration on the same infrastructure:

```python
import dataclasses as dc
from reconflux.core import DataclassMixin
from reconflux.net.http import HTTPIntegration, httpx_retry

@dc.dataclass(slots=True)
class MyResult(DataclassMixin):
    target: str
    data: dict

class MyIntegration(HTTPIntegration):
    def __init__(self) -> None:
        super().__init__('low_latency')

    @httpx_retry(attempts=3)
    async def fetch(self, target: str) -> MyResult:
        response = await self.client.get(f'/api/{target}')
        from reconflux.net.http import validate_response
        validate_response(response)
        return MyResult(target=target, data=response.json())
```

`HTTPIntegration` provides `self.client` (an `httpx.AsyncClient`), async context manager support (`async with MyIntegration() as i:`), and `aclose()`. `DataclassMixin` gives your result types `.asdict()`, `.replace()`, and `.fields()` for free.

To add a CLI command for your integration, follow the pattern in `reconflux/cli/`: define a `Typer` app, a components dataclass for Rich rendering, a console dataclass for output, async fetcher functions that return typed results, and synchronous command functions that call `anyio.run(fetcher, ...)` then render.

---

## Module Reference

| Module | Purpose |
|--------|---------|
| `reconflux.net.http` | `ClientOptions` builder, `new_async_httpx_client`, `HTTPIntegration`, `httpx_retry`, `validate_response`, `HttpPerformancePreset` |
| `reconflux.net.dns` | `DNSClient`, `DNSClientOptions`, `DNSRecordType`, `DNSQueryResult`, `HostResolutionResult`, `ReverseLookupResult` |
| `reconflux.net.tls` | `fetch_tls_certificate_sync`, `TLSClientOptions`, `TLSCertificateResult` |
| `reconflux.net.rdap` | `RDAPBootstrap`, RDAP response models, normalized record types |
| `reconflux.integrations.dns` | `DNSProvider`, `DNSLookupRequest`, `DomainDNSResult`, `EmailDNSResult`, `ReverseDNSResult` |
| `reconflux.integrations.rdap` | `RDAPProvider` — domain/IP/ASN RDAP lookups |
| `reconflux.integrations.ip_info` | `IPInfoProvider` — legacy and lite ipinfo.io lookups |
| `reconflux.integrations.tls` | `TLSIntegration`, `TLSBatchResult` |
| `reconflux.integrations.certsh` | `CertshIntegration`, `SubdomainResult` |
| `reconflux.integrations.web_scraper` | `WebScraperIntegration`, `WebScrapeResult`, `BatchWebScrapeResult` |
| `reconflux.integrations.files` | `FileAnalysisIntegration` — PDF, DOCX, XLSX, PPTX, image, audio |
| `reconflux.integrations.phone_numbers` | `PhoneNumberIntegration` — validation, E.164, carrier/region |
| `reconflux.web_scrapers` | `HydrationScraper`, `ScriptTagScrapper`, `URLScraper`, `analyze_html_head` — usable standalone |
| `reconflux.concurrency` | `run_concurrently`, `TaskExecutor`, `TaskPlanner`, `TaskExecutorResult`, `TimeSensitiveRunner` |
| `reconflux.core` | `ReconfluxModel`, `DataclassMixin`, `ReconfluxError`, `emit_internal_warning` |

---

## Roadmap

### Planned Integrations

- **WhatsMyName** — Username enumeration across hundreds of platforms, ported as a first-class integration. Async concurrent site probing, typed result model per platform, CLI command `reconflux username <handle>`. Site definitions will be maintained as versioned data rather than hardcoded logic.

- **Shodan** — Host and network search via the Shodan API: open ports, service banners, CVEs, and historical scan data.

- **HaveIBeenPwned** — Email/password breach checking via the HIBP API.

### Meterpreter-style TUI

The sheer number of knobs each integration exposes — nameservers, EDNS, TCP fallback, HTTP presets, referral depth, concurrency limits, fail-fast behavior, token auth — makes a flat CLI increasingly unwieldy for deep investigation sessions. The planned TUI is a persistent, session-based interface inspired by Metasploit's `meterpreter` / `msf` console model:

- Module selection (dns, whois, web, tls, external, files, …)
- Per-module option context (`set target github.com`, `set optimization high_throughput`)
- Live query execution with Rich output in a scrollable pane
- Session history and result export (JSON / CSV)
- Multi-target workflows — define a list of targets once, fan out across all active modules

This replaces the current pattern of repeating `--url`, `--host`, `--optimization`, etc. on every invocation with a stateful session where options persist until changed.

---

## Requirements

- Python >= 3.14
- uv (recommended)

---

## License

TBD
