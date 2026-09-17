#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "fpdf2>=2.7",
#   "python-pptx>=1.0",
#   "openpyxl>=3.1",
# ]
# ///
"""生成 benchmarks/corpus 下的最小真实语料（PDF/DOCX/PPTX/XLSX 各一）。

内容刻意覆盖 golden set v0 的六类场景：中文术语、英文/数字型号、跨结构块、
同义表达、空结果反例与多来源混合召回。只在重生成语料时手动运行：

    uv run benchmarks/corpus/create_corpus.py

依赖：脚本头内联声明 fpdf2/python-pptx/openpyxl（uv 自动装入隔离环境），
DOCX 由外部 pandoc 进程生成。PDF 用 fpdf2 生成规范单字节字体文档——
手工裸写 PDF 会被 docling 的版面模型宽容降级，页边界不可靠。
"""

from __future__ import annotations

from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent


def build_pdf(path: Path) -> None:
    """两页真实 PDF：页 1 讲 RAG/bge-m3，页 2 讲 RTX-4090 选型。"""
    from fpdf import FPDF

    pages = [
        "Quarterly Technology Report. Retrieval-Augmented Generation, RAG, "
        "architecture overview. The hybrid retrieval pipeline combines BM25 "
        "keyword search with dense vector embeddings from BAAI/bge-m3.",
        "Model selection. The team standardised on NVIDIA RTX-4090 GPUs with "
        "128GB memory for local inference benchmarks.",
    ]
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=16)
    for text in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(0, 8, text)
    pdf.output(str(path))


def build_pptx(path: Path) -> None:
    from pptx import Presentation
    from pptx.util import Inches

    slides = [
        ("四库产品规划", "本地优先的个人知识库，覆盖万能摄取、检索与自然语言问答。"),
        ("混合召回策略", "BM25 全文检索与向量召回双路融合，bge-reranker 重排提升精度。"),
        ("上线节奏", "Phase 2 检索纵切面交付 golden set 基线，随后进入图谱阶段。"),
    ]
    presentation = Presentation()
    blank = presentation.slide_layouts[6]
    for title, body in slides:
        slide = presentation.slides.add_slide(blank)
        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.6), Inches(8.0), Inches(1.2))
        title_box.text_frame.text = title
        body_box = slide.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(8.0), Inches(3.0))
        body_box.text_frame.text = body
    presentation.save(str(path))


def build_xlsx(path: Path) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    budget = workbook.active
    budget.title = "预算"
    budget.append(["项目", "型号", "数量", "金额"])
    budget.append(["显卡", "RTX-4090", 2, 31984])
    budget.append(["内存", "128GB DDR5", 4, 8192])
    budget.append(["存储", "NVMe 4TB", 2, 3596])
    staffing = workbook.create_sheet("人力")
    staffing.append(["角色", "人数", "周期"])
    staffing.append(["算法工程师", 2, "6个月"])
    staffing.append(["数据标注", 3, "2个月"])
    workbook.save(str(path))


def build_docx(path: Path) -> None:
    import subprocess
    import tempfile

    markdown = (
        "# 知识库工程笔记\n\n"
        "## 知识图谱构建方法\n\n"
        "实体抽取与关系抽取完成后进行社区发现，图谱数据落盘为 parquet，"
        "支持按 source_hash 全量重建。\n\n"
        "## 问答系统评测\n\n"
        "检索质量使用 Recall@5 与 MRR@10 指标衡量，golden set 回归是合入门禁。\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as handle:
        handle.write(markdown)
        temp_name = handle.name
    try:
        subprocess.run(
            ["pandoc", temp_name, "-o", str(path)],
            check=True,
            capture_output=True,
            encoding="utf-8",
        )
    finally:
        Path(temp_name).unlink(missing_ok=True)


def main() -> None:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    build_pdf(CORPUS_DIR / "demo-report.pdf")
    build_pptx(CORPUS_DIR / "demo-slides.pptx")
    build_xlsx(CORPUS_DIR / "demo-budget.xlsx")
    build_docx(CORPUS_DIR / "demo-notes.docx")
    for item in sorted(CORPUS_DIR.iterdir()):
        print(item.name)


if __name__ == "__main__":
    main()
