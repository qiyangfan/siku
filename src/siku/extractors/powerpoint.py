"""PowerPoint Extractor。"""

from pathlib import Path

from siku.extractors.models import ExtractedBlock, ExtractedDocument, ExtractorError


class PowerPointExtractor:
    """python-pptx 幻灯片适配器。"""

    suffixes: tuple[str, ...] = (".pptx",)

    def extract(self, source_path: Path) -> ExtractedDocument:
        try:
            from pptx import Presentation
        except ImportError as exc:
            raise ExtractorError(
                "PowerPoint extraction requires the optional 'ingest-office' dependency."
            ) from exc
        presentation = Presentation(str(source_path))
        blocks: list[ExtractedBlock] = []
        for index, slide in enumerate(presentation.slides, start=1):
            texts = [
                getattr(shape, "text", "").strip()
                for shape in slide.shapes
                if getattr(shape, "text", "").strip()
            ]
            text = "\n\n".join(value for value in texts if value)
            if text:
                blocks.append(ExtractedBlock(text, f"slide:{index}"))
        if not blocks:
            raise ExtractorError(f"No readable content was extracted from {source_path.name}.")
        return ExtractedDocument(source_path.stem, tuple(blocks))
