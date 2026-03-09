# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                  # install dependencies + build package (registers CLI script)
uv run reconflux         # run the CLI
uv run ruff check .      # lint
uv run ruff format .     # format
uv run ruff check --fix  # lint + auto-fix
```

There is no test suite yet. Python 3.14+ is required.

## Architecture

### Layer model

```
reconflux/
├── net/          # Low-level async clients (DNS, HTTP, TLS)
├── integrations/ # High-level OSINT workflows built on net/
├── cli/          # Typer commands that call integrations
├── concurrency.py
├── core/         # Base models, errors, warnings
├── app/          # Logging config, appdata path resolution
├── files/        # File reading/analysis (PDF, DOCX, XLSX, …)
└── web_scrapers/ # HTML/JS scraping utilities
```

The dependency direction is strict: `cli → integrations → net → core`. Nothing in `net/` or `integrations/` imports from `cli/`.

### net/ — low-level clients

- `net/http/` — `ClientOptions` builder (fluent API via `.performance_preset()`, `.use_common_headers()`, etc.) → `new_async_httpx_client()`. Retry logic lives in `_retry.py` as the `@httpx_retry(attempts=N)` decorator backed by tenacity.
- `net/dns/` — `DNSClient` wrapping dnspython's async resolver. `DNSClientOptions` controls nameservers, EDNS, TCP, timeout, lifetime, etc.
- `net/tls/` — synchronous TLS certificate inspection.

### integrations/ — OSINT workflows

Each integration is a dataclass that owns an HTTP/DNS client and exposes async methods returning typed result dataclasses (all inherit `DataclassMixin`).

- `dns.py` — `DNSIntegration`: domain record fan-out, reverse PTR, email DNS (MX/SPF/DMARC), DNSBL blocklist checks. Uses `TaskExecutor` / `run_concurrently` for concurrent queries. `DNSLookupRequest` → `dispatch()` routes to the correct workflow.
- `ip_info.py` — `IPInfoClient`: `.lite_search()` (free enriched endpoint) and `.legacy_search()` (unauthenticated basic). `IpLiteRecord` / `IpRecord` are the result types. `ip_info_clientmaker(token=…)` constructs the httpx client.
- `certsh.py` — `CertshIntegration.get_subdomains()` → `SubdomainResult`.

### cli/ — Typer commands

- `app.py` — `create_cli_app()` assembles the top-level `Typer` and registers sub-apps.
- `dns.py` — `dns_app` with a single `lookup` command. `DNSCommandOptions` (Pydantic model extending `DNSClientOptions`) validates the mutually-exclusive target flags. Rendering is done by standalone `render_*` functions using Rich `Table`, `Panel`, `Group`.
- `net.py` — `net_app` with `certsh` and `ipinfo` commands. Two dedicated classes:
  - `NetRenderer` — dataclass, all Rich output methods (`certsh`, `ip_lite`, `ip_legacy`, `error`). Shared static helpers `_kv_table` and `_row`.
  - `IntegrationRunner` — dataclass holding a `NetRenderer`, async methods `run_certsh` / `run_ip_info`.
  - Commands instantiate `IntegrationRunner()` locally and wrap `anyio.run(…)` with `cli_exception_guard` from `cli/utils.py`.
- `utils.py` — `cli_exception_guard(message)` context manager: catches `KeyboardInterrupt` → exit 130, any other exception → prints a red Rich panel and exits 1.

### concurrency.py

`TaskPlanner` (NamedTuple: `fail_fast`, `deadline`, `limiter`) + `TaskExecutor` (dataclass: `schedule: dict[str, Input]`, `runner: Callable`) → `TaskExecutorResult(results, errors)`. Top-level helper: `run_concurrently(schedule, runner, *, fail_fast, concurrency_limit, timeout)`.

### core/

- `ReconfluxModel` — Pydantic `BaseModel` with `extra='forbid'`, `str_strip_whitespace=True`, `validate_assignment=True`.
- `DataclassMixin` — adds `.asdict()`, `.astuple()`, `.replace()`, `.fields()` to result dataclasses.
- `ReconfluxError` / `FileSystemError` / `ReconfluxValidationError` — structured error hierarchy with `.message`, `.context`, `error_code`.

### Conventions

- All integration result types are `@dc.dataclass(slots=True)` + `DataclassMixin`.
- Pydantic models (settings, request/response validation) extend `ReconfluxModel`.
- HTTP clients are built via `ClientOptions(base_url=…).performance_preset(…).use_common_headers(…)` → `new_async_httpx_client(options)`.
- Boolean positional args in async runners get `# noqa: FBT001` (ruff enforces no bare bool params).
- Line length is 90. Single quotes throughout. Ruff auto-fix is enabled with `unsafe-fixes = true`.
