"""摄取模块的稳定领域模型与适配器协议。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ExtractedBlock:
    """一个带可选原文锚点的结构化正文块。"""

    text: str
    anchor: str | None = None


@dataclass(frozen=True)
class ExtractedDocument:
    """格式适配器输出的格式无关文档。"""

    title: str
    blocks: tuple[ExtractedBlock, ...]


class ExtractorError(RuntimeError):
    """格式适配器无法完成抽取时抛出的领域错误。"""


class ScannedPdfError(ExtractorError):
    """整份 PDF 没有可抽取文本（典型为扫描件），需要先 OCR 或转换。"""


class EncryptedDocumentError(ExtractorError):
    """文档已加密，无法在不知口令的情况下打开。"""


class CorruptDocumentError(ExtractorError):
    """文件不是声称格式的可解析文档（损坏或伪装扩展名）。"""


class ConverterUnavailableError(ExtractorError):
    """外部转换工具（如 pandoc）不可用：随包资源缺失且系统 PATH 无该工具。"""


@runtime_checkable
class Extractor(Protocol):
    """每个源格式必须实现的最小抽取协议。"""

    suffixes: tuple[str, ...]

    def extract(self, source_path: Path) -> ExtractedDocument:
        """从源文件生成结构化文档。"""
