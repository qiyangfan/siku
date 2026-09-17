"""PDF Extractor。"""

from pathlib import Path

from siku.extractors.common import one_block
from siku.extractors.models import ExtractedBlock, ExtractedDocument, ExtractorError


class PdfExtractor:
    """Docling PDF 适配器。"""

    suffixes: tuple[str, ...] = (".pdf",)

    def extract(self, source_path: Path) -> ExtractedDocument:
        try:
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import (
                DocumentConverter,
                InputFormat,
                PdfFormatOption,
            )
        except ImportError as exc:
            raise ExtractorError(
                "PDF extraction requires the optional 'ingest-pdf' dependency."
            ) from exc
        options = PdfPipelineOptions(do_ocr=False, do_table_structure=False)
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
        document = converter.convert(str(source_path)).document
        blocks: list[ExtractedBlock] = []
        for page_no in sorted(getattr(document, "pages", {})):
            text = document.export_to_markdown(page_no=page_no).strip()
            if text:
                blocks.append(ExtractedBlock(text, f"page:{page_no}"))
        if blocks:
            full_text = "\n\n".join(block.text for block in blocks)
            title = one_block(source_path, full_text).title
            return ExtractedDocument(title=title, blocks=tuple(blocks))
        return one_block(source_path, document.export_to_markdown())
