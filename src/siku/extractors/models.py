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


@runtime_checkable
class Extractor(Protocol):
    """每个源格式必须实现的最小抽取协议。"""

    suffixes: tuple[str, ...]

    def extract(self, source_path: Path) -> ExtractedDocument:
        """从源文件生成结构化文档。"""
