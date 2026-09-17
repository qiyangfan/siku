"""格式适配器测试。"""

import sys
import types
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest

from siku.extractors import (
    ExcelExtractor,
    HtmlExtractor,
    PdfExtractor,
    PowerPointExtractor,
    WordExtractor,
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


def test_word_extractor_uses_external_pandoc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"docx")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> types.SimpleNamespace:
        calls.append(command)
        return types.SimpleNamespace(returncode=0, stdout="# 标题\n\n正文", stderr="")

    monkeypatch.setattr("siku.extractors.word.subprocess.run", fake_run)

    document = WordExtractor().extract(source)

    assert calls[0][:3] == ["pandoc", str(source), "-t"]
    assert document.blocks[0].text.startswith("# 标题")


def test_pdf_extractor_loads_docling_lazily(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "report.pdf"
    source.write_bytes(b"pdf")

    class FakeDocument:
        pages: ClassVar[dict[int, object]] = {1: object()}

        def export_to_markdown(self, page_no: int | None = None) -> str:
            return "# PDF\n\n正文"

    class FakeConverter:
        def __init__(self, **kwargs: Any) -> None:
            assert "format_options" in kwargs

        def convert(self, path: str) -> types.SimpleNamespace:
            assert path == str(source)
            return types.SimpleNamespace(document=FakeDocument())

    parent = types.ModuleType("docling")
    datamodel = types.ModuleType("docling.datamodel")
    pipeline_options = types.ModuleType("docling.datamodel.pipeline_options")
    module = types.ModuleType("docling.document_converter")
    pipeline_options.__dict__["PdfPipelineOptions"] = lambda **kwargs: kwargs
    module.__dict__["DocumentConverter"] = FakeConverter
    module.__dict__["InputFormat"] = types.SimpleNamespace(PDF="pdf")
    module.__dict__["PdfFormatOption"] = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "docling", parent)
    monkeypatch.setitem(sys.modules, "docling.datamodel", datamodel)
    monkeypatch.setitem(sys.modules, "docling.datamodel.pipeline_options", pipeline_options)
    monkeypatch.setitem(sys.modules, "docling.document_converter", module)

    document = PdfExtractor().extract(source)

    assert document.blocks[0].anchor == "page:1"
    assert "PDF" in document.blocks[0].text


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


def test_epub_extractor_reads_html_members(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("OEBPS/chapter.xhtml", "<h1>章节</h1><p>内容</p>")

    from siku.extractors import EpubExtractor

    document = EpubExtractor().extract(source)

    assert document.blocks[0].anchor == "chapter:chapter"
    assert "内容" in document.blocks[0].text
