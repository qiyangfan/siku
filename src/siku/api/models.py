"""HTTP API 的请求和响应模型。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from siku.retrieve.models import SearchOptions


class ErrorResponse(BaseModel):
    """统一错误响应。"""

    code: str
    message: str


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str
    version: str


class IngestRequest(BaseModel):
    """摄取请求。"""

    source: Path
    vault: Path | None = None


class IngestResponse(BaseModel):
    """来源级摄取统计。"""

    created: int
    updated: int
    skipped: int
    ignored: int


class SearchRequest(BaseModel):
    """检索请求。"""

    query: str
    top_k: int = Field(default=SearchOptions.top_k, ge=1)
    candidate_k: int = Field(default=SearchOptions.candidate_k, ge=1)


class SearchResultResponse(BaseModel):
    """带来源锚点和阶段分数的检索结果。"""

    chunk_id: str
    source_name: str
    note_path: str
    source_hash: str
    anchor: str
    text: str
    bm25_score: float | None
    vector_score: float | None
    hybrid_score: float
    rerank_score: float


class SearchResponse(BaseModel):
    """与 `siku search --json` 同构的检索响应。"""

    query: str
    top_k: int
    candidate_k: int
    results: list[SearchResultResponse]


class GraphRequest(BaseModel):
    """图谱构建请求。"""

    vault: Path | None = None
    data_dir: Path | None = None
    rebuild: bool = False


class GraphExtractorResponse(BaseModel):
    """图谱抽取器身份。"""

    id: str
    model: str
    prompt_version: str


class GraphResponse(BaseModel):
    """与 `siku graph --json` 同构的体检报告。"""

    chunks: int
    nodes: int
    edges: int
    communities: int
    ambiguous_entities: int
    cache_hits: int
    llm_calls: int
    warnings: list[str]
    empty_corpus: bool
    extractor: GraphExtractorResponse


class WikiRequest(BaseModel):
    """wiki 生成请求。"""

    data_dir: Path | None = None


class WikiResponse(BaseModel):
    """与 `siku wiki --json` 同构的生成统计。"""

    entries: int
    cache_hits: int
    llm_calls: int
    empty_graph: bool
