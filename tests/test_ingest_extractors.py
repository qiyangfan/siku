"""格式适配器测试（默认轻量运行时，ADR-0013）。"""

import shutil
import sys
import types
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tests.document_fixtures import (
    make_corrupt_pdf,
    make_docx,
    make_encrypted_pdf,
    make_pptx,
    make_text_pdf,
    make_textless_pdf,
    make_xlsx,
)

from siku.extractors import (
    ExcelExtractor,
    HtmlExtractor,
    PdfExtractor,
    PowerPointExtractor,
    WordExtractor,
)
from siku.extractors.models import (
    CorruptDocumentError,
    EncryptedDocumentError,
    ScannedPdfError,
)


def test_html_extractor_returns_visible_text(tmp_path: Path) -> None:
    source = tmp_path / "page.html"
    source.write_text("<h1>标题</h1><p>正文</p><script>隐藏</script>", encoding="utf-8")

    document = HtmlExtractor().extract(source)

    assert document.title == "标题"
    assert "正文" in document.blocks[0].text
    assert "隐藏" not in document.blocks[0].text


def test_html_extractor_uses_filename_without_heading(tmp_path: Path) -> None:
    source = tmp_path / "page.html"
    source.write_text("<p>正文</p>", encoding="utf-8")

    document = HtmlExtractor().extract(source)

    assert document.title == "page"


def test_html_extractor_ignores_empty_heading_and_keeps_body(tmp_path: Path) -> None:
    source = tmp_path / "page.html"
    source.write_text("<h1></h1><p>正文</p>", encoding="utf-8")

    document = HtmlExtractor().extract(source)

    assert document.title == "page"
    assert document.blocks[0].text == "正文"


# ---- PDF（默认 pypdf 适配器，无需可选依赖） ----


def test_pdf_extractor_reads_mixed_language_text_with_page_anchors(tmp_path: Path) -> None:
    source = make_text_pdf(
        tmp_path / "报告.pdf",
        ["第一页：中文与 English 混排", "Page two: plain text"],
    )

    document = PdfExtractor().extract(source)

    assert [block.anchor for block in document.blocks] == ["page:1", "page:2"]
    assert "中文" in document.blocks[0].text
    assert "English" in document.blocks[0].text
    assert "Page two" in document.blocks[1].text


def test_pdf_extractor_keeps_original_page_numbers_across_blank_pages(
    tmp_path: Path,
) -> None:
    source = make_text_pdf(
        tmp_path / "空白中页.pdf",
        ["第一页正文", None, "第三页正文"],
    )

    document = PdfExtractor().extract(source)

    # 空白中间页不产生块，也不得让后续页重编号
    assert [block.anchor for block in document.blocks] == ["page:1", "page:3"]


def test_pdf_extractor_without_text_fails_actionably(tmp_path: Path) -> None:
    source = make_textless_pdf(tmp_path / "扫描件.pdf")

    with pytest.raises(ScannedPdfError) as excinfo:
        PdfExtractor().extract(source)

    assert "OCR" in str(excinfo.value)


def test_pdf_extractor_rejects_corrupt_file(tmp_path: Path) -> None:
    source = make_corrupt_pdf(tmp_path / "损坏.pdf")

    with pytest.raises(CorruptDocumentError):
        PdfExtractor().extract(source)


def test_pdf_extractor_rejects_encrypted_file(tmp_path: Path) -> None:
    source = make_encrypted_pdf(tmp_path / "加密.pdf", "机密内容", "s3cret")

    with pytest.raises(EncryptedDocumentError):
        PdfExtractor().extract(source)


# ---- Word（pandoc 经统一运行时定位） ----


def test_word_extractor_uses_resolved_pandoc_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "报告.docx"
    source.write_bytes(b"docx")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> types.SimpleNamespace:
        calls.append(command)
        return types.SimpleNamespace(returncode=0, stdout="# 标题\n\n正文", stderr="")

    monkeypatch.setattr("siku.extractors.pandoc_runtime.bundled_pandoc_path", lambda: None)
    monkeypatch.setattr(
        "siku.extractors.pandoc_runtime.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr("siku.extractors.word.subprocess.run", fake_run)

    document = WordExtractor().extract(source)

    assert calls[0][0] == "/usr/bin/pandoc"
    assert calls[0][1:] == [str(source), "-t", "gfm", "--wrap=none"]
    assert document.blocks[0].text.startswith("# 标题")


def test_word_extractor_prefers_bundled_pandoc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """冻结形态：随包资源优先于系统 PATH，绝对路径不经 shell。"""
    bundled = tmp_path / "resources" / "pandoc" / "bin" / "pandoc"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"#!/bin/sh\n")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> types.SimpleNamespace:
        calls.append(command)
        return types.SimpleNamespace(returncode=0, stdout="正文", stderr="")

    monkeypatch.setenv("SIKU_TEST_PANDOC_ROOT", str(tmp_path / "resources"))
    monkeypatch.setattr(
        "siku.extractors.pandoc_runtime.shutil.which",
        lambda name: pytest.fail("must not consult PATH when bundled resource exists"),
    )
    monkeypatch.setattr("siku.extractors.word.subprocess.run", fake_run)

    document = WordExtractor().extract(tmp_path / "doc.docx")

    assert calls[0][0] == str(bundled)
    assert document.blocks[0].text == "正文"


def test_word_extractor_requires_docx_suffix_only() -> None:
    """旧二进制 .doc 不在适配器范围：pandoc 不承诺读取该格式。"""
    assert WordExtractor.suffixes == (".docx",)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not on PATH")
def test_word_extractor_converts_real_docx(tmp_path: Path) -> None:
    source = make_docx(tmp_path / "真实.docx", "# 标题\n\n正文段落")

    document = WordExtractor().extract(source)

    assert document.title == "标题"
    assert "正文段落" in document.blocks[0].text


# ---- PPTX / XLSX / XLSM（核心运行时结构夹具） ----


def test_powerpoint_extractor_emits_slide_anchors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"pptx")

    class Shape:
        def __init__(self, text: str) -> None:
            self.text = text

    class Presentation:
        def __init__(self, path: str) -> None:
            assert path == str(source)
            self.slides = [types.SimpleNamespace(shapes=[Shape("第一张")])]

    module = types.ModuleType("pptx")
    module.__dict__["Presentation"] = Presentation
    monkeypatch.setitem(sys.modules, "pptx", module)

    document = PowerPointExtractor().extract(source)

    assert document.blocks[0].anchor == "slide:1"
    assert document.blocks[0].text == "第一张"


def test_powerpoint_extractor_reads_real_pptx(tmp_path: Path) -> None:
    source = make_pptx(tmp_path / "演示.pptx", ["第一张要点", "", "第三张要点"])

    document = PowerPointExtractor().extract(source)

    assert [block.anchor for block in document.blocks] == ["slide:1", "slide:3"]
    assert document.blocks[0].text == "第一张要点"


def test_excel_extractor_emits_sheet_anchors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.xlsx"
    source.write_bytes(b"xlsx")

    class Worksheet:
        title = "数据"

        def iter_rows(self, values_only: bool) -> Iterator[tuple[object, ...]]:
            assert values_only is True
            return iter([("列一", "列二"), ("值", 2)])

    module = types.ModuleType("openpyxl")

    def load_workbook(**kwargs: Any) -> types.SimpleNamespace:
        return types.SimpleNamespace(worksheets=[Worksheet()], close=lambda: None)

    module.__dict__["load_workbook"] = load_workbook
    monkeypatch.setitem(sys.modules, "openpyxl", module)

    document = ExcelExtractor().extract(source)

    assert document.blocks[0].anchor == "sheet:数据"
    assert "| 列一 | 列二 |" in document.blocks[0].text


def test_excel_extractor_reads_real_multisheet_workbook(tmp_path: Path) -> None:
    source = make_xlsx(
        tmp_path / "工作簿.xlsx",
        {"数据": [["列一", "列二"], ["值", 2]], "汇总": [["合计", 3]]},
    )

    document = ExcelExtractor().extract(source)

    assert [block.anchor for block in document.blocks] == ["sheet:数据", "sheet:汇总"]
    assert "| 值 | 2 |" in document.blocks[0].text


def test_excel_extractor_reads_xlsm_without_executing_macros(tmp_path: Path) -> None:
    """XLSM 可读表格支持保持；宏不存在也不被执行（ADR-0013 边界）。"""
    source = make_xlsx(tmp_path / "宏表.xlsm", {"数据": [["列一"], ["值"]]})

    document = ExcelExtractor().extract(source)

    assert document.blocks[0].anchor == "sheet:数据"
    assert "值" in document.blocks[0].text


def test_epub_extractor_reads_html_members(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("OEBPS/chapter.xhtml", "<h1>章节</h1><p>内容</p>")

    from siku.extractors import EpubExtractor

    document = EpubExtractor().extract(source)

    assert document.blocks[0].anchor == "chapter:chapter"
    assert "内容" in document.blocks[0].text
