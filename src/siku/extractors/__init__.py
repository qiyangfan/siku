"""统一的文档 Extractor 协议与格式适配器。"""

from siku.extractors.epub import EpubExtractor
from siku.extractors.excel import ExcelExtractor
from siku.extractors.html import HtmlExtractor
from siku.extractors.markdown import MarkdownExtractor
from siku.extractors.models import (
    ConverterUnavailableError,
    CorruptDocumentError,
    EncryptedDocumentError,
    ExtractedBlock,
    ExtractedDocument,
    Extractor,
    ExtractorError,
    ScannedPdfError,
)
from siku.extractors.pdf import PdfExtractor
from siku.extractors.powerpoint import PowerPointExtractor
from siku.extractors.registry import extractor_registry, legacy_office_target
from siku.extractors.word import WordExtractor

__all__ = [
    "ConverterUnavailableError",
    "CorruptDocumentError",
    "EncryptedDocumentError",
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
    "ScannedPdfError",
    "WordExtractor",
    "extractor_registry",
    "legacy_office_target",
]
