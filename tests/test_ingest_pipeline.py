"""摄取流水线测试。"""

from pathlib import Path

import pytest

from siku.extractors import ExtractedBlock, ExtractedDocument, Extractor
from siku.ingest.pipeline import IngestError, ingest_path


class FakeTextExtractor:
    suffixes: tuple[str, ...] = (".txt",)

    def extract(self, source_path: Path) -> ExtractedDocument:
        return ExtractedDocument(
            title=source_path.stem,
            blocks=(ExtractedBlock(source_path.read_text(encoding="utf-8"), "page:1"),),
        )


def test_ingest_writes_attachment_and_deterministic_markdown(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("第一版", encoding="utf-8")
    vault = tmp_path / "vault"

    first = ingest_path(source, vault, {".txt": FakeTextExtractor()})
    item = first.items[0]

    assert first.created == 1
    assert item.attachment_path.read_bytes() == source.read_bytes()
    first_note = item.note_path.read_bytes()
    assert b"source_hash:" in first_note
    assert "page:1" in item.note_path.read_text(encoding="utf-8")

    second = ingest_path(source, vault, {".txt": FakeTextExtractor()})

    assert second.skipped == 1
    assert item.note_path.read_bytes() == first_note
    assert len(list((vault / "notes").glob("*.md"))) == 1
    assert len(list((vault / "attachments").glob("*"))) == 1


def test_ingest_repairs_a_corrupted_attachment(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("原件", encoding="utf-8")
    vault = tmp_path / "vault"
    extractors = {".txt": FakeTextExtractor()}

    first = ingest_path(source, vault, extractors)
    attachment = first.items[0].attachment_path
    attachment.write_text("损坏副本", encoding="utf-8")

    repaired = ingest_path(source, vault, extractors)

    assert repaired.updated == 1
    assert attachment.read_text(encoding="utf-8") == "原件"


def test_empty_extractor_registry_does_not_fallback_to_defaults(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("内容", encoding="utf-8")

    report = ingest_path(source, tmp_path / "vault", {})

    assert report.created == 0
    assert report.ignored_paths == (source.resolve(),)


def test_ingest_rejects_a_symlinked_attachment(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("原件", encoding="utf-8")
    vault = tmp_path / "vault"
    extractors = {".txt": FakeTextExtractor()}
    first = ingest_path(source, vault, extractors)
    attachment = first.items[0].attachment_path
    outside = tmp_path / "outside.txt"
    outside.write_text("外部文件", encoding="utf-8")
    attachment.unlink()
    attachment.symlink_to(outside)

    with pytest.raises(IngestError, match="vault symlink"):
        ingest_path(source, vault, extractors)

    assert outside.read_text(encoding="utf-8") == "外部文件"


def test_changed_source_updates_only_its_projection(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    other = tmp_path / "other.txt"
    source.write_text("第一版", encoding="utf-8")
    other.write_text("另一个文件", encoding="utf-8")
    vault = tmp_path / "vault"
    extractors: dict[str, Extractor] = {".txt": FakeTextExtractor()}

    initial = ingest_path(tmp_path, vault, extractors)
    source_item = next(item for item in initial.items if item.source_path == source)
    other_item = next(item for item in initial.items if item.source_path == other)
    source.write_text("第二版", encoding="utf-8")

    changed = ingest_path(tmp_path, vault, extractors)

    assert changed.updated == 1
    assert changed.skipped == 1
    assert (
        source_item.note_path
        == next(item for item in changed.items if item.source_path == source).note_path
    )
    assert "第二版" in source_item.note_path.read_text(encoding="utf-8")
    assert "另一个文件" in other_item.note_path.read_text(encoding="utf-8")
    assert len(list((vault / "notes").glob("*.md"))) == 2


def test_directory_ingest_ignores_unknown_suffixes(tmp_path: Path) -> None:
    supported = tmp_path / "supported.txt"
    ignored = tmp_path / "ignored.bin"
    supported.write_text("内容", encoding="utf-8")
    ignored.write_bytes(b"binary")

    report = ingest_path(tmp_path, tmp_path / "vault", {".txt": FakeTextExtractor()})

    assert report.created == 1
    assert report.ignored == 1
    assert report.ignored_paths == (ignored,)


# ---- 旧二进制 Office 格式的可行动拒绝（ADR-0013） ----


def test_single_file_ingest_rejects_legacy_office_with_conversion_hint(
    tmp_path: Path,
) -> None:
    from siku.ingest.pipeline import LegacyOfficeFormatError

    source = tmp_path / "旧文档.doc"
    source.write_bytes(b"legacy binary")

    with pytest.raises(LegacyOfficeFormatError) as excinfo:
        ingest_path(source, tmp_path / "vault", {".txt": FakeTextExtractor()})

    assert ".docx" in str(excinfo.value)


def test_directory_ingest_treats_legacy_office_as_ignored(tmp_path: Path) -> None:
    """目录模式维持既有「不认识即忽略」口径：批量场景不因单个旧文件中断。"""
    legacy = tmp_path / "旧文档.xls"
    legacy.write_bytes(b"legacy binary")

    report = ingest_path(tmp_path, tmp_path / "vault", {".txt": FakeTextExtractor()})

    assert report.ignored == 1
    assert report.ignored_paths == (legacy,)


# ---- 适配器类型化错误翻译为摄取层类型化错误 ----


@pytest.mark.parametrize(
    ("extractor_error", "ingest_error"),
    [
        ("siku.extractors.models.ScannedPdfError", "ScannedPdfIngestError"),
        ("siku.extractors.models.EncryptedDocumentError", "EncryptedDocumentIngestError"),
        ("siku.extractors.models.CorruptDocumentError", "CorruptDocumentIngestError"),
        (
            "siku.extractors.models.ConverterUnavailableError",
            "ConverterUnavailableIngestError",
        ),
    ],
)
def test_typed_extractor_errors_keep_their_class_through_the_pipeline(
    tmp_path: Path, extractor_error: str, ingest_error: str
) -> None:
    import importlib

    from siku.extractors.models import ExtractorError

    module_path, _, class_name = extractor_error.rpartition(".")
    raised = getattr(importlib.import_module(module_path), class_name)
    expected = getattr(importlib.import_module("siku.ingest.pipeline"), ingest_error)

    class RaisingExtractor:
        suffixes: tuple[str, ...] = (".txt",)

        def extract(self, source_path: Path) -> ExtractedDocument:
            raise raised("boom")

    source = tmp_path / "file.txt"
    source.write_text("内容", encoding="utf-8")

    with pytest.raises(expected):
        ingest_path(source, tmp_path / "vault", {".txt": RaisingExtractor()})
    assert issubclass(expected, IngestError)
    assert issubclass(raised, ExtractorError)


def test_default_pdf_pipeline_roundtrip_keeps_page_anchors(tmp_path: Path) -> None:
    """默认注册表下的 PDF 真实端到端：投影含 page 锚点与 frontmatter。"""
    from tests.document_fixtures import make_text_pdf

    source = make_text_pdf(tmp_path / "报告.pdf", ["第一页", None, "第三页"])

    report = ingest_path(source, tmp_path / "vault")

    note_text = report.items[0].note_path.read_text(encoding="utf-8")
    assert "## page:1" in note_text
    assert "## page:3" in note_text
    assert "page:2" not in note_text
