"""EPUB Extractor。"""

import zipfile
from pathlib import Path

from siku.extractors.common import parse_html
from siku.extractors.models import ExtractedBlock, ExtractedDocument, ExtractorError


class EpubExtractor:
    """EPUB 内 XHTML 文档适配器。"""

    suffixes: tuple[str, ...] = (".epub",)

    def extract(self, source_path: Path) -> ExtractedDocument:
        blocks: list[ExtractedBlock] = []
        title = source_path.stem
        with zipfile.ZipFile(source_path) as archive:
            members = sorted(
                name
                for name in archive.namelist()
                if name.lower().endswith((".html", ".htm", ".xhtml"))
            )
            for member in members:
                heading, text = parse_html(archive.read(member).decode("utf-8"))
                if text.strip():
                    title = heading or title
                    blocks.append(ExtractedBlock(text.strip(), f"chapter:{Path(member).stem}"))
        if not blocks:
            raise ExtractorError(f"No readable content was extracted from {source_path.name}.")
        return ExtractedDocument(title=title, blocks=tuple(blocks))
