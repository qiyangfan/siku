"""格式适配器注册表。"""

from siku.extractors.epub import EpubExtractor
from siku.extractors.excel import ExcelExtractor
from siku.extractors.html import HtmlExtractor
from siku.extractors.markdown import MarkdownExtractor
from siku.extractors.models import Extractor
from siku.extractors.pdf import PdfExtractor
from siku.extractors.powerpoint import PowerPointExtractor
from siku.extractors.word import WordExtractor

# 旧二进制 Office 格式 → 对应现代格式的转换指引（ADR-0013：不再宣称可直接抽取）
_LEGACY_OFFICE_TARGETS: dict[str, str] = {
    ".doc": ".docx",
    ".ppt": ".pptx",
    ".xls": ".xlsx",
}


def legacy_office_target(suffix: str) -> str | None:
    """旧二进制 Office 后缀对应的现代格式；非旧格式返回 None。"""
    return _LEGACY_OFFICE_TARGETS.get(suffix.lower())


def extractor_registry() -> dict[str, Extractor]:
    """返回扩展名到格式适配器的注册表。"""
    extractors: tuple[Extractor, ...] = (
        MarkdownExtractor(),
        HtmlExtractor(),
        EpubExtractor(),
        PdfExtractor(),
        WordExtractor(),
        PowerPointExtractor(),
        ExcelExtractor(),
    )
    return {suffix: extractor for extractor in extractors for suffix in extractor.suffixes}
