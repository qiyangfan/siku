"""Word Extractor。"""

import subprocess
from pathlib import Path

from siku.extractors.common import one_block
from siku.extractors.models import ExtractedDocument, ExtractorError


class WordExtractor:
    """通过外部 pandoc 进程抽取 Word。"""

    suffixes: tuple[str, ...] = (".doc", ".docx")

    def extract(self, source_path: Path) -> ExtractedDocument:
        try:
            result = subprocess.run(
                ["pandoc", str(source_path), "-t", "gfm", "--wrap=none"],
                check=False,
                capture_output=True,
                encoding="utf-8",
                text=True,
            )
        except FileNotFoundError as exc:
            raise ExtractorError("Word extraction requires the 'pandoc' executable.") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or "pandoc returned a non-zero exit code"
            raise ExtractorError(f"Word extraction failed: {detail}")
        return one_block(source_path, result.stdout)
