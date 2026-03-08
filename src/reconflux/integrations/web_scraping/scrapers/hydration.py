import dataclasses as dc
import re
from typing import TYPE_CHECKING, Any, Literal, Self

import bs4

from reconflux.integrations.web_scraping.scrapers import parser_utils

if TYPE_CHECKING:
    from collections.abc import Generator


type WindowVarType = Literal['hydration', 'inline']


def get_default_hydration_selectors() -> set[str]:
    return {
        'script#__NEXT_DATA__',
        'script#__NUXT_DATA__',
    }


def is_dunder(var_name: str) -> bool:
    return var_name.startswith('__') and var_name.endswith('__')


def get_default_window_regexes() -> list[re.Pattern]:
    patterns = [
        r'window\.(__\w+__)\s*=\s*({[^<]*?});',
        r'window\.(\w+State)\s*=\s*({[^<]*?});',
        r'window\.(\w+Data)\s*=\s*({[^<]*?});',
        r'(\w+)\s*=\s*({(?:[^{}]|{[^}]*})*})\s*;',
    ]
    return [re.compile(pattern, re.MULTILINE | re.DOTALL) for pattern in patterns]


@dc.dataclass(slots=True)
class HyrdationSelectorScrapper:
    hydration_selectors: set[str] = dc.field(
        default_factory=get_default_hydration_selectors,
        init=False,
    )
    errors: list[str] = dc.field(default_factory=list, init=False)

    def update_selectors(self, *selectors: str) -> Self:
        self.hydration_selectors.update(selectors)
        return self

    def select_suspected_hydration(
        self,
        soup: bs4.BeautifulSoup,
        selector: str,
    ) -> tuple[str, dict | list]:
        tag_id = f'json-hydrated({selector})'
        tag = soup.select_one(selector)
        if '#' in selector and tag:
            tag_id = selector.split('#', 1)[1]

        if not tag:
            return tag_id, {}

        content = tag.string or tag.get_text() or ''
        parsed, error = parser_utils.try_json_loads(content)
        if error:
            self.errors.append(error)

        return tag_id, parsed or {}

    def iter_selector_hits(
        self,
        soup: bs4.BeautifulSoup,
    ) -> Generator[tuple[str, dict | list]]:
        for selector in self.hydration_selectors:
            yield self.select_suspected_hydration(soup, selector)


@dc.dataclass(slots=True)
class ScrappedWindowVariable:
    label: WindowVarType
    variable_name: str
    blob: dict[str, Any] | list[dict[str, Any]]


@dc.dataclass(slots=True)
class WindowVariableScrapper:
    window_regexes: list[re.Pattern] = dc.field(
        default_factory=get_default_window_regexes
    )
    errors: list[str] = dc.field(default_factory=list)

    def extend_patterns(self, *patterns: str, flags: re.RegexFlag | int = 0) -> Self:
        self.window_regexes.extend([re.compile(pattern, flags) for pattern in patterns])
        return self

    def _scaniter_patterns(self, text: str) -> Generator[re.Match[str]]:
        for pattern in self.window_regexes:
            yield from pattern.finditer(text)

    def parse_window_match(self, match: re.Match[str]) -> ScrappedWindowVariable | None:
        var_name, json_blob = match.groups()
        parsed_blob, error = parser_utils.try_json_loads(json_blob)
        if error:
            self.errors.append(error)

        if not parsed_blob:
            return None

        variable_type = 'hydration' if is_dunder(var_name) else 'inline'
        return ScrappedWindowVariable(
            variable_name=var_name,
            blob=parsed_blob,
            label=variable_type,
        )

    def scaniter_window_vars(self, text: str) -> Generator[ScrappedWindowVariable]:
        for match in self._scaniter_patterns(text):
            hydration_iterable = self.parse_window_match(match)
            if hydration_iterable:
                yield hydration_iterable


@dc.dataclass(slots=True)
class HydrationScrapperResults:
    window_variables: list[ScrappedWindowVariable]
    selector_matches: dict[str, list[dict] | dict]


def analyze_site_hydration(
    soup: bs4.BeautifulSoup,
    response_text: str,
    *,
    window_variable: WindowVariableScrapper | None = None,
    selector: HyrdationSelectorScrapper | None = None,
) -> HydrationScrapperResults:
    window_scraper = window_variable or WindowVariableScrapper()
    selector = selector or HyrdationSelectorScrapper()

    selector_matches = dict(selector.iter_selector_hits(soup))
    window_variables = list(window_scraper.scaniter_window_vars(response_text))

    return HydrationScrapperResults(
        window_variables=window_variables, selector_matches=selector_matches
    )
