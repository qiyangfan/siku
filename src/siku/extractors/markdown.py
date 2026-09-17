"""Markdown Extractor。"""

from pathlib import Path

from siku.extractors.common import one_block
from siku.extractors.models import ExtractedDocument


class MarkdownExtractor:
    """Markdown 原文适配器。"""

    suffixes: tuple[str, ...] = (".md", ".markdown")

    def extract(self, source_path: Path) -> ExtractedDocument:
        return one_block(source_path, source_path.read_text(encoding="utf-8"))
