import dataclasses as dc
from typing import Self

import bs4


def get_tag_attribute(tag: bs4.Tag, *candidates: str) -> str | None:
    for attr in candidates:
        if candidate := tag.get(attr):
            return str(candidate).strip()

    return None


@dc.dataclass(slots=True)
class HeadAnalyzerRuleset:
    security_meta_tag_names: set[str] = dc.field(default_factory=set)
    cdn_indicators: set[str] = dc.field(default_factory=set)
    url_tag_attributes: set[str] = dc.field(default_factory=set)

    def merge(self, other: HeadAnalyzerRuleset) -> None:
        self.cdn_indicators.update(other.cdn_indicators)
        self.security_meta_tag_names.update(other.security_meta_tag_names)
        self.url_tag_attributes.update(other.url_tag_attributes)

    def is_cdn_like(self, url: str, tag: bs4.Tag) -> bool:
        if get_tag_attribute(tag, 'crossorigin') is not None:
            return True

        return any(indicator in url for indicator in self.cdn_indicators)

    def is_css_like(self, tag: bs4.Tag) -> bool:
        if tag.name != 'link':
            return False

        if not (rel := get_tag_attribute(tag, 'rel')):
            return False

        return 'stylesheet' in rel.lower().split()


@dc.dataclass(slots=True)
class PackageGroups:
    css: list[str] = dc.field(default_factory=list)
    javascript: list[str] = dc.field(default_factory=list)
    cdn_like: list[str] = dc.field(default_factory=list)

    @classmethod
    def from_soup(cls, soup: bs4.BeautifulSoup, ruleset: HeadAnalyzerRuleset) -> Self:
        assert soup.head
        packages = cls()

        for notable_tag in soup.head.find_all(['link', 'script']):
            potential_url = get_tag_attribute(notable_tag, *ruleset.url_tag_attributes)
            if not potential_url:
                continue

            if notable_tag.name == 'link' and ruleset.is_css_like(notable_tag):
                packages.css.append(potential_url)

            elif notable_tag.name == 'script':
                packages.javascript.append(potential_url)

            if ruleset.is_cdn_like(potential_url, notable_tag):
                packages.cdn_like.append(potential_url)

        return packages


@dc.dataclass(slots=True)
class CommonMetaTags:
    charset: str | None = None
    description: str | None = None
    keywords: str | None = None
    robots: str | None = None

    @classmethod
    def from_soup(cls, soup: bs4.BeautifulSoup) -> Self:
        assert soup.head
        keys = dc.fields(cls)
        kwargs: dict[str, str | None] = {key.name: None for key in keys}
        for attrs in kwargs:
            meta_tag = soup.head.find('meta', attrs={'name': attrs})
            if not meta_tag:
                meta_tag = soup.head.find('meta', attrs={'property': attrs})

            if meta_tag and (content := get_tag_attribute(meta_tag, 'content')):
                kwargs[attrs] = content

        return cls(**kwargs)


@dc.dataclass(slots=True)
class MetaTagCategories:
    open_graph: dict[str, str] = dc.field(default_factory=dict)
    security: dict[str, str] = dc.field(default_factory=dict)
    extras: dict[str, str] = dc.field(default_factory=dict)

    def add_metatag(self, meta_tag: bs4.Tag, security_meta_tag_names: set[str]) -> None:
        if not (prop := get_tag_attribute(meta_tag, 'name', 'property')):
            return

        prop = prop.lower()
        tag_contents = get_tag_attribute(meta_tag, 'content')
        if not tag_contents:
            return

        if prop.startswith('og:'):
            self.open_graph[prop] = tag_contents
            return

        if prop in security_meta_tag_names:
            self.security[prop] = tag_contents
            return

        self.extras[prop] = tag_contents


@dc.dataclass(slots=True)
class WebsiteHeadData:
    common: CommonMetaTags
    categories: MetaTagCategories
    packages: PackageGroups

    @classmethod
    def extract_with_ruleset(
        cls, soup: bs4.BeautifulSoup, ruleset: HeadAnalyzerRuleset
    ) -> Self:
        common = CommonMetaTags.from_soup(soup)
        packages = PackageGroups.from_soup(soup, ruleset)
        categories = MetaTagCategories()
        assert soup.head
        for meta_tag in soup.head.find_all('meta'):
            categories.add_metatag(
                meta_tag,
                ruleset.security_meta_tag_names,
            )

        return cls(
            common=common,
            categories=categories,
            packages=packages,
        )


def get_default_ruleset() -> HeadAnalyzerRuleset:
    security_meta_tag_names = {
        'http-equiv',
        'x-content-type-options',
        'content-security-policy',
        'strict-transport-security',
        'referrer',
    }
    cdn_indicators = {
        'cdn.',
        '.cdn.',
        'cdnjs.cloudflare.com',
        'jsdelivr.net',
        'ajax.googleapis.com',
        'maxcdn.bootstrapcdn.com',
        'code.jquery.com',
        'unpkg.com',
    }
    url_tag_attributes = {
        'src',
        'href',
        'data-src',
        'data-href',
    }
    return HeadAnalyzerRuleset(
        security_meta_tag_names=security_meta_tag_names,
        cdn_indicators=cdn_indicators,
        url_tag_attributes=url_tag_attributes,
    )


def analyze_html_head(
    soup: bs4.BeautifulSoup, *, extended_ruleset: HeadAnalyzerRuleset | None = None
) -> WebsiteHeadData:
    ruleset = get_default_ruleset()
    if extended_ruleset:
        ruleset.merge(extended_ruleset)

    return WebsiteHeadData.extract_with_ruleset(soup, ruleset)
