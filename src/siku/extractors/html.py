"""HTML Extractor。"""

from pathlib import Path

from siku.extractors.common import parse_html
from siku.extractors.models import ExtractedBlock, ExtractedDocument, ExtractorError


class HtmlExtractor:
    """HTML 可见文本适配器。"""

    suffixes: tuple[str, ...] = (".html", ".htm")

    def extract(self, source_path: Path) -> ExtractedDocument:
        heading, text = parse_html(source_path.read_text(encoding="utf-8"))
        if not text.strip():
            raise ExtractorError(f"No readable content was extracted from {source_path.name}.")
        return ExtractedDocument(
            title=heading or source_path.stem,
            blocks=(ExtractedBlock(text.strip()),),
        )
