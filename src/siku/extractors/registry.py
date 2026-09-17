"""格式适配器注册表。"""

from siku.extractors.epub import EpubExtractor
from siku.extractors.excel import ExcelExtractor
from siku.extractors.html import HtmlExtractor
from siku.extractors.markdown import MarkdownExtractor
from siku.extractors.models import Extractor
from siku.extractors.pdf import PdfExtractor
from siku.extractors.powerpoint import PowerPointExtractor
from siku.extractors.word import WordExtractor


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
