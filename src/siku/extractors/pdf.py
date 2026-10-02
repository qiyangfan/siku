"""PDF Extractor（默认轻量实现，ADR-0013）。

用 pypdf 的公开文本提取接口逐页抽取，保留原始页序锚点；不引入布局模型、
OCR 或任何首次运行下载。整份无可抽取文本（典型为扫描件）按可行动失败返回，
不伪造空投影。
"""

import logging
from pathlib import Path

from siku.extractors.common import one_block
from siku.extractors.models import (
    CorruptDocumentError,
    EncryptedDocumentError,
    ExtractedBlock,
    ExtractedDocument,
    ScannedPdfError,
)

logger = logging.getLogger(__name__)

# 每页文本的清理规则：去掉 pypdf 提取中常见的零宽字符；保留其余空白结构
_INVISIBLE_CHARS = "\u200b\u200c\u200d\ufeff"


class PdfExtractor:
    """pypdf 文本 PDF 适配器。"""

    suffixes: tuple[str, ...] = (".pdf",)

    def extract(self, source_path: Path) -> ExtractedDocument:
        try:
            from pypdf import PasswordType, PdfReader
            from pypdf.errors import PdfReadError
        except ImportError as exc:  # pragma: no cover - pypdf 是核心依赖，防御性兜底
            raise CorruptDocumentError(
                "PDF extraction requires the core 'pypdf' dependency."
            ) from exc
        try:
            reader = PdfReader(str(source_path))
            # 空口令（仅 owner 密码）的 PDF 可正常读取；用户口令未提供则失败
            if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
                raise EncryptedDocumentError(
                    f"The PDF {source_path.name} is password-protected; "
                    "remove the password before importing it."
                )
            pages = list(reader.pages)
        except EncryptedDocumentError:
            raise
        except PdfReadError as exc:
            if "not been decrypted" in str(exc):
                raise EncryptedDocumentError(
                    f"The PDF {source_path.name} is password-protected; "
                    "remove the password before importing it."
                ) from exc
            raise CorruptDocumentError(
                f"The file {source_path.name} is not a readable PDF: {exc}"
            ) from exc
        blocks: list[ExtractedBlock] = []
        # 原始页序锚点：空白页不产生块，但后续页面按自身页号锚定，绝不重编号
        for page_number, page in enumerate(pages, start=1):
            try:
                raw_text = page.extract_text() or ""
            except PdfReadError as exc:
                raise CorruptDocumentError(
                    f"Failed to extract text from page {page_number} of {source_path.name}: {exc}"
                ) from exc
            text = raw_text.translate({ord(char): None for char in _INVISIBLE_CHARS}).strip()
            if text:
                blocks.append(ExtractedBlock(text, f"page:{page_number}"))
        if not blocks:
            raise ScannedPdfError(
                f"The PDF {source_path.name} contains no extractable text"
                " (it is likely a scanned document); convert it to a text-based PDF"
                " (e.g. with an OCR tool) before importing."
            )
        full_text = "\n\n".join(block.text for block in blocks)
        title = one_block(source_path, full_text).title
        return ExtractedDocument(title=title, blocks=tuple(blocks))
