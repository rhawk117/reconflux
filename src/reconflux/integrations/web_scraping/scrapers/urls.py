


import re
from typing import TYPE_CHECKING, Self

import bs4

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable

def get_default_url_patterns() -> list[str]:
    return [
        r'href="(/_next/data/[^"]+\.json)"',
        r'href="([^"]*?\.pageContext\.json)"',
        r'"url":\s*"([^"]+\.json)"',
        r'fetch\(["\']([^"\']+\.json)["\']',
    ]



class URLScraper:
    __slots__ = '_patterns'

    def register_patterns(
        self,
        patterns: Iterable[str],
        flags: re.RegexFlag | int = 0,
    ) -> Self:
        self._patterns.extend([re.compile(pattern, flags) for pattern in patterns])
        return self

    def __init__(self, *, defaults_okay: bool = True) -> None:
        self._patterns: list[re.Pattern] = []
        if defaults_okay:
            self.register_patterns(get_default_url_patterns())

    def scan_for_urls(self, response_text: str) -> Generator[str]:
        for pattern in self._patterns:
            yield from pattern.findall(response_text)

    def scan_anchors(self, base_url: str, soup: bs4.BeautifulSoup) -> Generator[str]:
        for a in soup.find_all('a', href=True):
            href = a['href']
            yield str(href)
