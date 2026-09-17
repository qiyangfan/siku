"""Excel Extractor。"""

from pathlib import Path
from typing import Any

from siku.extractors.models import ExtractedBlock, ExtractedDocument, ExtractorError


def _cell_text(value: Any) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


class ExcelExtractor:
    """openpyxl 工作表适配器。"""

    suffixes: tuple[str, ...] = (".xlsx", ".xlsm")

    def extract(self, source_path: Path) -> ExtractedDocument:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise ExtractorError(
                "Excel extraction requires the optional 'ingest-office' dependency."
            ) from exc
        workbook = load_workbook(filename=source_path, read_only=True, data_only=True)
        blocks: list[ExtractedBlock] = []
        try:
            for worksheet in workbook.worksheets:
                rows = [
                    [_cell_text(value) for value in row]
                    for row in worksheet.iter_rows(values_only=True)
                ]
                rows = [row for row in rows if any(row)]
                if not rows:
                    continue
                width = max(len(row) for row in rows)
                normalized = [row + [""] * (width - len(row)) for row in rows]
                lines = [f"| {' | '.join(row)} |" for row in normalized]
                lines.insert(1, f"| {' | '.join('---' for _ in range(width))} |")
                blocks.append(ExtractedBlock("\n".join(lines), f"sheet:{worksheet.title}"))
        finally:
            workbook.close()
        if not blocks:
            raise ExtractorError(f"No readable content was extracted from {source_path.name}.")
        return ExtractedDocument(source_path.stem, tuple(blocks))
