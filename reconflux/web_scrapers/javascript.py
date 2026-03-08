import dataclasses as dc
import re
from typing import TYPE_CHECKING, Literal, Self

import bs4

from reconflux.web_scrapers import parser_utils

if TYPE_CHECKING:
    from collections.abc import Generator

type UrlLabels = Literal['DOMFetch', 'XMLHttpRequest']

_JAVASCRIPT_FETCH = r"""
    fetch\(\s*(?P<q>
    `(?:\\.|[^`])*?` # template literal
    | "(?:\\.|[^"])*?" # double-quoted
    | '(?:\\.|[^'])*?' # single-quoted
    )
"""

_JAVASCRIPT_JSON_PARSE = r"""
    JSON\.parse\(\s*(?P<q>
    `\s*(?:\{[\s\S]*?\}|\[[\s\S]*?\])\s*`   # template literal containing JSON
    | "\s*(?:\{[\s\S]*?\}|\[[\s\S]*?\])\s*"   # double-quoted JSON
    | '\s*(?:\{[\s\S]*?\}|\[[\s\S]*?\])\s*'   # single-quoted JSON
    )\s*\)
"""

_JAVASCRIPT_XML_REQUEST = r"""
    (?:new\s+XMLHttpRequest\(\)|fetch\(\s*)\.open\(\s*(?P<q>
      `(?:\\.|[^`])*?` # template literal
    | "(?:\\.|[^"])*?" # double-quoted
    | '(?:\\.|[^'])*?' # single-quoted
    )
"""


@dc.dataclass(slots=True)
class JavascriptCodePatterns:
    fetch: re.Pattern
    json_parse: re.Pattern
    xhr: re.Pattern

    @classmethod
    def compile(cls) -> Self:
        opts = re.DOTALL | re.MULTILINE | re.VERBOSE
        return cls(
            fetch=re.compile(_JAVASCRIPT_FETCH, opts),
            json_parse=re.compile(_JAVASCRIPT_JSON_PARSE, opts),
            xhr=re.compile(_JAVASCRIPT_XML_REQUEST, opts),
        )


def _iter_regex_matches(js_text: str, pattern: re.Pattern) -> Generator[str]:
    for matches in pattern.finditer(js_text):
        if hit := matches.group('q'):
            yield hit


@dc.dataclass(slots=True)
class InlineScriptData:
    json_entites: list[str] = dc.field(default_factory=list)
    fetched_urls: dict[UrlLabels, set[str]] = dc.field(
        init=False,
        default_factory=dict,
    )

    def add_url(self, label: UrlLabels, url: str) -> None:
        url = url.strip('\'"` ')
        if not url:
            return

        self.fetched_urls.setdefault(label, set()).add(url)

    def scan_script_tag(self, tag: bs4.Tag, patterns: JavascriptCodePatterns) -> None:
        if not (js_text := tag.get_text()):
            return

        self.json_entites.extend(
            hyrdated_json_str
            for hyrdated_json_str in _iter_regex_matches(js_text, patterns.json_parse)
        )
        for match in _iter_regex_matches(js_text, patterns.fetch):
            self.add_url('DOMFetch', match)

        for match in _iter_regex_matches(js_text, patterns.xhr):
            self.add_url('XMLHttpRequest', match)


def get_dict_keys(current: dict | list, max_depth: int = 5, parent: str = '') -> set[str]:
    keys = set()
    if max_depth <= 0 or not isinstance(current, dict):
        return keys

    for key, value in current.items():
        cur_key = f'{parent}.{key}' if parent else key
        keys.add(cur_key)
        if isinstance(value, dict):
            keys.update(get_dict_keys(value, max_depth - 1, cur_key))
    return keys


@dc.dataclass(slots=True)
class ScriptJsonContent:
    parsed_content: dict | list
    data_keys: set[str] = dc.field(default_factory=set)


def is_json_like(content: str, tag_type: str | None) -> bool:
    if not content or not content.strip():
        return False

    json_content_types = ('application/ld+json', 'application/json')

    if tag_type and tag_type.lower() in json_content_types:
        return True

    stripped = content.lstrip()
    return stripped.startswith(('{', '['))


@dc.dataclass(slots=True)
class ScriptTagData:
    content: str = ''
    tag_type: str | None = None
    src: str | None = None
    inline_data: InlineScriptData | None = None
    json_data: ScriptJsonContent | None = None

    @property
    def content_length(self) -> int:
        return len(self.content) if self.content else 0

    def get_content_preview(self, max_chars: int = 100) -> str:
        if not self.content:
            return '[no_content]'

        preview = re.sub(r'\s+', ' ', self.content.strip())[:max_chars]
        if self.content_length > max_chars:
            preview += '...'

        return preview

    def is_empty(self) -> bool:
        return not self.content


@dc.dataclass(slots=True)
class ScriptTagScrapper:
    regexes: JavascriptCodePatterns = dc.field(
        default_factory=JavascriptCodePatterns.compile
    )

    def _set_script_json_content(self, metadata: ScriptTagData) -> ScriptTagData:
        parsed, _error = parser_utils.try_json_loads(metadata.content.strip())
        if not parsed:
            return metadata

        metadata.json_data = ScriptJsonContent(
            data_keys=get_dict_keys(parsed), parsed_content=parsed
        )
        return metadata

    def _set_script_inline_metadata(
        self,
        script_tag: bs4.Tag,
        metadata: ScriptTagData,
    ) -> ScriptTagData:
        metadata.inline_data = InlineScriptData()
        metadata.inline_data.scan_script_tag(script_tag, self.regexes)
        return metadata

    def analyze_script_tag(self, script_tag: bs4.Tag) -> ScriptTagData:
        tag_type = script_tag.get('type')
        content = script_tag.string or script_tag.get_text() or ''
        metadata = ScriptTagData(
            tag_type=str(tag_type),
            content=content,
            src=str(script_tag.get('src', '[none]')),
        )
        if metadata.is_empty():
            return metadata

        if is_json_like(content, metadata.tag_type):
            return self._set_script_json_content(metadata)

        return self._set_script_inline_metadata(script_tag, metadata)

    def analyze_script_tags(self, script_tags: list[bs4.Tag]) -> list[ScriptTagData]:
        return [self.analyze_script_tag(script_tag) for script_tag in script_tags]
