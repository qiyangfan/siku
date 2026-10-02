"""本地文档摄取能力。"""

from siku.ingest.pipeline import (
    ConverterUnavailableIngestError,
    CorruptDocumentIngestError,
    EncryptedDocumentIngestError,
    IngestError,
    IngestReport,
    LegacyOfficeFormatError,
    ScannedPdfIngestError,
    ingest_path,
)

__all__ = [
    "ConverterUnavailableIngestError",
    "CorruptDocumentIngestError",
    "EncryptedDocumentIngestError",
    "IngestError",
    "IngestReport",
    "LegacyOfficeFormatError",
    "ScannedPdfIngestError",
    "ingest_path",
]
