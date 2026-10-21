"""测试用真实文档夹具生成（reportlab / python-pptx / openpyxl / pandoc）。

生成结构合法、可被真实解析器读取的文档，不伪造二进制字节。
"""

from __future__ import annotations

import io
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches
from pypdf import PdfReader, PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

_CID_FONT = "STSong-Light"


def _render_pdf(pages: Sequence[str | None]) -> bytes:
    """按页渲染文本 PDF；页元素为 None 时产出无正文的空白页。"""
    pdfmetrics.registerFont(UnicodeCIDFont(_CID_FONT))
    buffer = io.BytesIO()
    renderer = canvas.Canvas(buffer)
    for text in pages:
        if text is not None:
            renderer.setFont(_CID_FONT, 12)
            renderer.drawString(72, 720, text)
        renderer.showPage()
    renderer.save()
    return buffer.getvalue()


def make_text_pdf(path: Path, pages: Sequence[str | None]) -> Path:
    """生成含文本的 PDF（页序即 pages；None 表示空白中间页）。"""
    path.write_bytes(_render_pdf(pages))
    return path


def make_textless_pdf(path: Path, page_count: int = 1) -> Path:
    """生成无任何可抽取文本的 PDF（模拟扫描件/纯图片）。"""
    path.write_bytes(_render_pdf([None] * page_count))
    return path


def make_encrypted_pdf(path: Path, text: str, password: str) -> Path:
    """生成带用户口令的加密 PDF。"""
    source = PdfReader(io.BytesIO(_render_pdf([text])))
    writer = PdfWriter()
    for page in source.pages:
        writer.add_page(page)
    writer.encrypt(password)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def make_corrupt_pdf(path: Path) -> Path:
    """生成损坏 PDF（魔数在、正文结构坏）。"""
    path.write_bytes(b"%PDF-1.4\nbroken-not-a-real-xref\n%%EOF\n")
    return path


def make_pptx(path: Path, slide_texts: Sequence[str]) -> Path:
    """生成含文本框的 PPTX；空字符串产出空白幻灯片。"""
    presentation = Presentation()
    blank_layout = presentation.slide_layouts[6]
    for text in slide_texts:
        slide = presentation.slides.add_slide(blank_layout)
        if text:
            box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(2))
            box.text_frame.text = text
    presentation.save(path)
    return path


def make_xlsx(path: Path, sheets: dict[str, list[list[object]]]) -> Path:
    """生成多 sheet 工作簿（.xlsx / .xlsm 由扩展名决定）。"""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        worksheet = workbook.create_sheet(title=title)
        for row in rows:
            worksheet.append(row)
    workbook.save(path)
    return path


def make_docx(path: Path, markdown: str) -> Path | None:
    """经系统 pandoc 从 Markdown 生成结构真实的 DOCX；无 pandoc 返回 None。"""
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        return None
    result = subprocess.run(
        [pandoc, "-f", "gfm", "-t", "docx", "-o", str(path)],
        input=markdown,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not path.exists():
        return None
    return path
