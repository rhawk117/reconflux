# reconflux

A highly performant, modern, asynchronous Python open source intelligence (OSINT) framework.

Built on Python 3.14+ with `anyio`, `httpx`, `dnspython`, and `pydantic` at its core. Designed for concurrent, structured intelligence gathering across DNS, IP, TLS, file systems, and more.

---

## Features

### Net
- **DNS** — Full record enumeration (A, AAAA, CNAME, MX, NS, PTR, SOA, SRV, TXT, CAA), reverse lookups, and async resolution via `dnspython`
- **TLS** — Synchronous TLS certificate inspection: issuer, subject, SANs, validity window, serial number
- **HTTP** — Async `httpx` client with retry logic, HTTP/2 support, and response validation helpers

### Integrations
- **DNS Integration** — Concurrent domain record enumeration, PTR reverse search, email DNS analysis (MX/SPF/DMARC), and DNSBL blocklist checking
- **IP Info** — Three ipinfo.io integration tiers: legacy unauthenticated, lite unauthenticated (enriched), and token-authenticated full lookup
- **Phone Numbers** — Validation, E.164 formatting, country/region/operator lookup via `phonenumbers`
- **Cert.sh** — Subdomain enumeration via certificate transparency logs (crt.sh)

### Files
- Structured file analysis and reading across document types: PDF, DOCX, XLSX, PPTX, images, audio, and more

### Concurrency
- `collect_concurrently`, `map_concurrently`, `dispatch_tasks` — task group primitives built on `anyio`
- `DispatchableTask` — abstract base for named async tasks
- `ConcurrencyIntegrationMixin` — composable mixin for integration classes
- `ExecutionMode.FAIL_FAST` / `BEST_EFFORT` — configurable error handling strategies
- `ConcurrentResults[T]` — typed result container with per-task failure tracking

### Core
- `DataclassMixin` — shared base for dataclass results
- `ReconfluxModel` — pydantic base model with consistent config
- Structured error hierarchy, settings, warnings, and rich formatting utilities

---

## Requirements

- Python >= 3.14
- uv (recommended for dependency management)

---

## Installation

```bash
uv sync
```

---

## Usage

```python
import asyncio
from reconflux.integrations.dns import DNSIntegration

async def main():
    dns = DNSIntegration()
    record = await dns.search("example.com")
    print(record.a)  # A records
    print(record.mx)  # MX records

    email = await dns.search_email("user@example.com")
    print(email.spf, email.dmarc)

asyncio.run(main())
```

```python
from reconflux.integrations.ip_info import IPInfoLiteIntegration
import asyncio

async def main():
    ip_info = IPInfoLiteIntegration()
    record = await ip_info.get_ip_record("8.8.8.8")
    print(record.country_name, record.org, record.maps_link)

asyncio.run(main())
```

```python
from reconflux.integrations.phone_numbers import get_phone_info

record = get_phone_info("+14155552671")
print(record.country, record.operator, record.e164)
```

```python
import asyncio
from reconflux.integrations.certsh import CertshProvider

async def main():
    provider = CertshProvider()
    result = await provider.get_subdomain("example.com")
    print(result.total, result.subdomains[:5])

asyncio.run(main())
```

```python
from reconflux.net.tls import fetch_tls_certificate_sync

cert = fetch_tls_certificate_sync("example.com")
print(cert.issued_by, cert.valid_until, cert.subject_alternative_names)
```

---

## Project Structure

```
src/reconflux/
├── concurrency/      # Async task primitives (anyio-backed)
├── core/             # Base models, errors, settings, rich utils
├── files/            # File reading and analysis
├── integrations/     # High-level OSINT integrations
│   ├── certsh.py     # crt.sh subdomain enumeration
│   ├── dns.py        # DNS enumeration, reverse search, email, DNSBL
│   ├── ip_info.py    # IP geolocation (ipinfo.io)
│   └── phone_numbers.py
├── logging/          # Logging config and core
├── net/
│   ├── dns/          # Low-level async DNS client
│   ├── http/         # httpx client, retry, options
│   └── tls/          # TLS certificate fetching
└── web_scrapers/     # HTML/JS scraping utilities
```

---

## Roadmap — v1.0.0

### Integrations
- [ ] Get all integrations fully operational and covered with tests
  - [ ] `dns` — verify all record types, DNSBL, email DNS
  - [ ] `ip_info` — test all three tiers (legacy, lite, authenticated)
  - [ ] `phone_numbers` — edge cases and invalid number handling
  - [ ] `certsh` — pagination, large domain cert sets
- [ ] Shodan integration
- [ ] WHOIS integration
- [ ] HaveIBeenPwned integration
- [ ] Username search / social media presence integration

### CLI / TUI
- [ ] Build a CLI with `click` or `typer` for single-shot queries
  - [ ] `reconflux dns <domain>`
  - [ ] `reconflux ip <address>`
  - [ ] `reconflux tls <hostname>`
  - [ ] `reconflux email <address>`
  - [ ] `reconflux phone <number>`
  - [ ] `reconflux subdomains <domain>`
- [ ] Build a full TUI (e.g. with `textual`) for interactive investigation sessions
  - [ ] Dashboard view with live query results
  - [ ] Drill-down panels per integration
  - [ ] Export results to JSON / CSV
- [ ] Record and replay sessions for demos

### Migration
- [ ] Migrate **whats-my-name** (username enumeration) into reconflux as a first-class integration
  - [ ] Port site definitions / data layer
  - [ ] Async concurrent site checking
  - [ ] Result model + CLI command (`reconflux username <handle>`)

### Quality
- [ ] Add test suite (pytest + anyio)
- [ ] Add CI pipeline (lint, type-check, tests)
- [ ] Publish to PyPI
- [ ] Write full API documentation

---

## License

TBD
