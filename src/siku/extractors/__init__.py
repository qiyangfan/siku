"""统一的文档 Extractor 协议与格式适配器。"""

from siku.extractors.epub import EpubExtractor
from siku.extractors.excel import ExcelExtractor
from siku.extractors.html import HtmlExtractor
from siku.extractors.markdown import MarkdownExtractor
from siku.extractors.models import ExtractedBlock, ExtractedDocument, Extractor, ExtractorError
from siku.extractors.pdf import PdfExtractor
from siku.extractors.powerpoint import PowerPointExtractor
from siku.extractors.registry import extractor_registry
from siku.extractors.word import WordExtractor

__all__ = [
    "EpubExtractor",
    "ExcelExtractor",
    "ExtractedBlock",
    "ExtractedDocument",
    "Extractor",
    "ExtractorError",
    "HtmlExtractor",
    "MarkdownExtractor",
    "PdfExtractor",
    "PowerPointExtractor",
    "WordExtractor",
    "extractor_registry",
]
