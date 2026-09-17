"""检索模块：从 Markdown 事实层构建可重建索引并提供混合检索。

公共 API 稳定面：领域模型、错误体系、同步与检索服务、provider 协议。
CLI（`siku index/search/evaluate-retrieval`）与未来 HTTP 层都构建在这组
类型之上。
"""

from siku.retrieve.errors import (
    EvaluationError,
    FtsUnavailableError,
    GoldenSetError,
    IndexCorruptError,
    IndexUnavailableError,
    InvalidQueryError,
    ModelConfigMismatchError,
    ModelNotAvailableError,
    NoteParseError,
    ProviderError,
    RetrievalError,
)
from siku.retrieve.indexer import sync_index
from siku.retrieve.models import (
    ChunkRecord,
    DocumentRecord,
    IndexReport,
    SearchOptions,
    SearchResult,
)
from siku.retrieve.service import SearchService

__all__ = [
    "ChunkRecord",
    "DocumentRecord",
    "EvaluationError",
    "FtsUnavailableError",
    "GoldenSetError",
    "IndexCorruptError",
    "IndexReport",
    "IndexUnavailableError",
    "InvalidQueryError",
    "ModelConfigMismatchError",
    "ModelNotAvailableError",
    "NoteParseError",
    "ProviderError",
    "RetrievalError",
    "SearchOptions",
    "SearchResult",
    "SearchService",
    "sync_index",
]
