"""摄取领域模型与协议测试。"""

from pathlib import Path

from siku.extractors import ExtractedBlock, ExtractedDocument, Extractor, extractor_registry


def test_extracted_document_keeps_structural_anchors() -> None:
    document = ExtractedDocument(
        title="示例",
        blocks=(ExtractedBlock(text="正文", anchor="page:1"),),
    )

    assert document.title == "示例"
    assert document.blocks[0].anchor == "page:1"


def test_extractors_cover_phase_one_formats() -> None:
    registry = extractor_registry()

    assert isinstance(registry[".pdf"], Extractor)
    assert {".pdf", ".docx", ".pptx", ".xlsx"}.issubset(registry)
    assert registry[".epub"] is not None


def test_extractor_protocol_accepts_structural_implementation() -> None:
    class FakeExtractor:
        suffixes = (".txt",)

        def extract(self, source_path: Path) -> ExtractedDocument:
            return ExtractedDocument(source_path.stem, (ExtractedBlock("text"),))

    assert isinstance(FakeExtractor(), Extractor)
