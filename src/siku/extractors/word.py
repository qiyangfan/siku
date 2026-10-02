"""Word Extractor（DOCX 经 pandoc，ADR-0013 随包/系统工具定位）。

旧二进制 ``.doc`` 不在本适配器范围：pandoc 不承诺读取该格式，注册它只会把
「不支持」伪装成「转换失败」。旧格式的转换指引由摄取入口的校验层给出。
"""

import subprocess
from pathlib import Path

from siku.extractors.common import one_block
from siku.extractors.models import (
    ConverterUnavailableError,
    CorruptDocumentError,
    ExtractedDocument,
    ExtractorError,
)
from siku.extractors.pandoc_runtime import resolve_pandoc_command

# 单文件转换的受管超时：文档级转换不应无限占用任务槽
_PANDOC_TIMEOUT_SECS = 120


class WordExtractor:
    """通过外部 pandoc 进程抽取 DOCX。"""

    suffixes: tuple[str, ...] = (".docx",)

    def extract(self, source_path: Path) -> ExtractedDocument:
        command = resolve_pandoc_command()
        try:
            result = subprocess.run(
                [
                    *command,
                    str(source_path),
                    "-t",
                    "gfm",
                    "--wrap=none",
                ],
                check=False,
                capture_output=True,
                encoding="utf-8",
                text=True,
                timeout=_PANDOC_TIMEOUT_SECS,
            )
        except FileNotFoundError as exc:
            raise ConverterUnavailableError(
                "The pandoc converter disappeared before launch; retry the import."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ExtractorError(
                f"Word conversion of {source_path.name} timed out after"
                f" {_PANDOC_TIMEOUT_SECS}s; the document may be damaged or too large."
            ) from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or "pandoc returned a non-zero exit code"
            raise CorruptDocumentError(f"Word extraction failed for {source_path.name}: {detail}")
        return one_block(source_path, result.stdout)
