"""格式适配器共享的轻量解析辅助。"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from siku.extractors.models import ExtractedBlock, ExtractedDocument, ExtractorError


def one_block(path: Path, text: str, anchor: str | None = None) -> ExtractedDocument:
    """将一个完整文本转换为领域文档。"""
    cleaned = text.strip()
    if not cleaned:
        raise ExtractorError(f"No readable content was extracted from {path.name}.")
    title = path.stem
    for line in cleaned.splitlines():
        heading = re.match(r"^#\s+(.+?)\s*$", line)
        if heading:
            title = heading.group(1).strip()
            break
    return ExtractedDocument(title=title, blocks=(ExtractedBlock(cleaned, anchor),))


class VisibleTextParser(HTMLParser):
    """提取 HTML 可见文本和首个标题。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._heading_depth = 0
        self._heading: list[str] = []
        self._headings: list[str] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._hidden_depth += 1
        if tag in {"h1", "h2", "h3"} and self._hidden_depth == 0:
            self._heading_depth = 1
            self._heading = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1
        if tag in {"h1", "h2", "h3"} and self._heading_depth:
            if self._heading:
                heading = " ".join(self._heading)
                self._headings.append(heading)
                self._parts.append(heading)
            self._heading = []
            self._heading_depth = 0

    def handle_data(self, data: str) -> None:
        if self._hidden_depth or not data.strip():
            return
        text = " ".join(data.split())
        if self._heading_depth:
            self._heading.append(text)
        else:
            self._parts.append(text)

    @property
    def text(self) -> str:
        return "\n\n".join(part for part in self._parts if part)

    @property
    def first_heading(self) -> str | None:
        return self._headings[0] if self._headings else None


def parse_html(text: str) -> tuple[str | None, str]:
    """解析 HTML 可见文本。"""
    parser = VisibleTextParser()
    parser.feed(text)
    return parser.first_heading, parser.text
