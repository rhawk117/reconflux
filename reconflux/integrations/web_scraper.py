from __future__ import annotations

import dataclasses as dc
from typing import TYPE_CHECKING

import bs4
import httpx

from reconflux.concurrency import TaskExecutorResult, run_concurrently
from reconflux.core import DataclassMixin
from reconflux.net import http
from reconflux.web_scrapers import (
    HydrationScraper,
    HydrationScrapperResults,
    ScriptTagData,
    ScriptTagScrapper,
    URLScraper,
    WebsiteHeadData,
    analyze_html_head,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


@dc.dataclass(slots=True, frozen=True)
class WebScrapeResult(DataclassMixin):
    """Aggregated scraping output for a single URL.

    Parameters
    ----------
    url : str
        The URL that was fetched.
    status_code : int
        HTTP status code of the response.
    head : WebsiteHeadData
        Parsed ``<head>`` data: common meta tags, categorised meta tags,
        and discovered CSS / JS packages.
    hydration : HydrationScrapperResults
        Server-side hydration blobs found via selector and window-variable
        patterns (e.g. ``__NEXT_DATA__``, ``window.appState``).
    scripts : list[ScriptTagData]
        Per-``<script>`` tag analysis: inline JS patterns, JSON content,
        and external ``src`` references.
    anchors : list[str]
        Raw ``href`` values harvested from ``<a>`` tags.
    data_urls : list[str]
        Structured data URLs matched by the URL scraper patterns
        (e.g. Next.js page-data JSON paths).
    """
    url: str
    status_code: int
    head: WebsiteHeadData
    hydration: HydrationScrapperResults
    scripts: list[ScriptTagData]
    anchors: list[str]
    data_urls: list[str]


@dc.dataclass(slots=True, frozen=True)
class BatchWebScrapeResult(DataclassMixin):
    """Aggregate result for a concurrent multi-URL scrape.

    Parameters
    ----------
    results : TaskExecutorResult[WebScrapeResult]
        Per-URL scrape results and any per-URL errors.
    """

    results: TaskExecutorResult[WebScrapeResult]

    @property
    def succeeded(self) -> list[WebScrapeResult]:
        """Return results for URLs that were scraped successfully."""
        return list(self.results.results.values())

    @property
    def failed(self) -> dict[str, str]:
        """Return a mapping of URL to error representation."""
        return self.results.errors

    @property
    def total(self) -> int:
        """Return the total number of URLs attempted."""
        return len(self.results.results) + len(self.results.errors)

    @property
    def okay(self) -> bool:
        """Return whether every scrape completed without error."""
        return self.results.okay


def web_scraper_clientmaker(
    performance: http.HttpPerformancePreset = 'default',
) -> httpx.AsyncClient:
    """Create an ``httpx.AsyncClient`` with browser-like headers for web scraping."""
    options = (
        http
        .ClientOptions()
        .performance_preset(performance)
        .use_common_headers()
    )
    return http.new_async_httpx_client(options)


def scrape_http_response(
    url: str,
    response: httpx.Response,
    *,
    hydration_scraper: HydrationScraper | None = None,
    script_scraper: ScriptTagScrapper | None = None,
    url_scraper: URLScraper | None = None,
) -> WebScrapeResult:
    script_scraper = script_scraper or ScriptTagScrapper()
    url_scraper = url_scraper or URLScraper()
    hydration_scraper = hydration_scraper or HydrationScraper()

    html = response.text
    soup = bs4.BeautifulSoup(html, 'html.parser')

    head = analyze_html_head(soup)
    hydration = hydration_scraper.scrape_hydration(soup, html)
    scripts = script_scraper.analyze_script_tags(soup.find_all('script'))
    anchors = list(url_scraper.scan_anchors(url, soup))
    data_urls = list(url_scraper.scan_for_urls(html))

    return WebScrapeResult(
        url=url,
        status_code=response.status_code,
        head=head,
        hydration=hydration,
        scripts=scripts,
        anchors=anchors,
        data_urls=data_urls,
    )


class WebScraperIntegration(http.HTTPIntegration):
    """Reconflux web scraping integration.

    Fetches URLs asynchronously via ``httpx`` then runs the full suite of
    ``web_scrapers`` over the response HTML: head analysis, hydration blob
    extraction, per-script-tag analysis, and URL/anchor harvesting.

    Supports concurrent multi-URL scraping through the project's
    ``run_concurrently`` / ``TaskExecutor`` infrastructure.  The HTTP fetch
    is the primary bottleneck; BS4 parsing happens synchronously between
    awaits and does not stall other in-flight requests.

    Parameters
    ----------
    client : httpx.AsyncClient
        HTTP client used for all fetches. Defaults to a browser-like client
        built by ``web_scraper_clientmaker``.
    script_scraper : ScriptTagScrapper
        Scraper used to analyse individual ``<script>`` tags.
    url_scraper : URLScraper
        Scraper used to extract anchor hrefs and structured data URL patterns.
    """

    def __init__(
        self,
        performance: http.HttpPerformancePreset = 'default',
    ) -> None:
        client = web_scraper_clientmaker(performance)
        super().__init__(client)
        self.script_scraper = ScriptTagScrapper()
        self.url_scraper = URLScraper()
        self.hydration_scraper = HydrationScraper()

    @http.httpx_retry(attempts=3)
    async def _fetch(self, url: str) -> httpx.Response:
        response = await self.client.get(url)
        http.validate_response(response)
        return response


    async def scrape(self, url: str) -> WebScrapeResult:
        """Fetch and scrape a single URL.

        Parameters
        ----------
        url : str
            The URL to fetch and analyse.

        Returns
        -------
        WebScrapeResult
            Full scraping output for the URL.

        Raises
        ------
        HTTPError
            On non-2xx responses (after retries are exhausted).
        httpx.RequestError
            On network-level failures.
        """
        response = await self._fetch(url)
        return scrape_http_response(
            url=url,
            response=response,
            script_scraper=self.script_scraper,
            url_scraper=self.url_scraper,
        )

    async def scrape_many(
        self,
        urls: Iterable[str],
        *,
        concurrency_limit: int | None = None,
        timeout: float | None = None,  # noqa: ASYNC109
        fail_fast: bool = False,
    ) -> BatchWebScrapeResult:
        """Scrape multiple URLs concurrently.

        Parameters
        ----------
        urls : Iterable[str]
            URLs to fetch and analyse.
        concurrency_limit : int | None, default=None
            Maximum number of simultaneous fetches. ``None`` means no cap.
        timeout : float | None, default=None
            Wall-clock timeout in seconds applied across the entire batch.
        fail_fast : bool, default=False
            When ``True``, the first failed scrape cancels remaining tasks.
            When ``False``, errors are collected per-URL and the rest
            continue.

        Returns
        -------
        BatchWebScrapeResult
            Aggregate result with per-URL scrape data and any errors.
        """
        schedule = {url: url for url in urls}
        results = await run_concurrently(
            schedule=schedule,
            runner=self.scrape,
            concurrency_limit=concurrency_limit,
            timeout=timeout,
            fail_fast=fail_fast,
        )
        return BatchWebScrapeResult(results=results)
