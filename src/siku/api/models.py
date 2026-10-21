"""HTTP API 的请求和响应模型。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator

from siku.qa.models import MAX_CANDIDATE_K, MAX_QUESTION_CHARS, MAX_TOP_K
from siku.retrieve.models import SearchOptions


class ErrorResponse(BaseModel):
    code: str
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str


class IngestRequest(BaseModel):
    source: Path
    vault: Path | None = None


class IngestResponse(BaseModel):
    """单个来源的摄取统计。"""

    created: int
    updated: int
    skipped: int
    ignored: int


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=SearchOptions.top_k, ge=1)
    candidate_k: int = Field(default=SearchOptions.candidate_k, ge=1)


class SearchResultResponse(BaseModel):
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


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    top_k: int = Field(default=6, ge=1, le=MAX_TOP_K)
    candidate_k: int = Field(default=30, ge=1, le=MAX_CANDIDATE_K)

    @model_validator(mode="after")
    def validate_rank_limits(self) -> AskRequest:
        if self.top_k > self.candidate_k:
            raise ValueError("top_k must not exceed candidate_k")
        return self


class AskCitationResponse(BaseModel):
    citation_id: str
    source_name: str
    note_path: str
    anchor: str
    chunk_id: str
    source_hash: str
    text: str


class AskRetrievalResponse(BaseModel):
    top_k: int
    candidate_k: int
    result_count: int


class AskResponse(BaseModel):
    request_id: str
    question: str
    answer: str
    insufficient_evidence: bool
    citations: list[AskCitationResponse]
    retrieval: AskRetrievalResponse
    model: str


class GraphRequest(BaseModel):
    vault: Path | None = None
    data_dir: Path | None = None
    rebuild: bool = False


class GraphExtractorResponse(BaseModel):
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
    data_dir: Path | None = None


class WikiResponse(BaseModel):
    """与 `siku wiki --json` 同构的生成统计。"""

    entries: int
    cache_hits: int
    llm_calls: int
    empty_graph: bool


class ChannelSettingsView(BaseModel):
    """单通道掩码视图；`api_key` 只以 `api_key_set` 表示是否已设置。

    `protocol` 仅 LLM 通道使用；非法值在解析或提交校验时拒绝，不在视图层吞掉。
    """

    base_url: str | None
    model: str | None
    api_key_env: str | None
    protocol: str | None = None
    api_key_set: bool
    env_overrides: list[str]


class AskReadinessView(BaseModel):
    """问答就绪状态；`missing`/`invalid` 使用稳定的 `<channel>.<field>` token。

    `missing` 表示缺项，`invalid` 表示跨层合并后取值非法。判定与请求期通道解析
    同源；中文提示由 UI 根据 token 生成。
    """

    ready: bool
    missing: list[str]
    invalid: list[str] = Field(default_factory=list)


class LlmEnvFallbackView(BaseModel):
    """LLM 厂商环境变量回退的端点描述（不含凭证）。

    目前只有 `dashscope`；UI 据此说明回退生效时的实际端点。
    """

    vendor: str
    base_url: str
    model: str
    api_key_env: str


class SettingsResponse(BaseModel):
    """三个通道的掩码视图与问答就绪状态。"""

    config_path: str
    llm: ChannelSettingsView
    embedding: ChannelSettingsView
    rerank: ChannelSettingsView
    ask_readiness: AskReadinessView
    llm_env_fallback: LlmEnvFallbackView | None = None


class ChannelSettingsUpdate(BaseModel):
    """单通道提交值：省略字段表示保持现值，null 或空白表示清空，非空表示设置。

    ``api_key`` 只在非空时落盘，repr 与日志中均为掩码。
    """

    base_url: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None
    protocol: str | None = None


class SettingsUpdateRequest(BaseModel):
    """通道对象省略时，该通道保持不变。"""

    llm: ChannelSettingsUpdate | None = None
    embedding: ChannelSettingsUpdate | None = None
    rerank: ChannelSettingsUpdate | None = None


class SettingsWriteResponse(SettingsResponse):
    """保存后的掩码视图与重建告警。

    `invalid_config_file_overwritten=True` 表示保存前配置文件无法解析，已用空文件层
    合并请求并覆盖。正常写入恒为 False。
    """

    warnings: list[str]
    invalid_config_file_overwritten: bool = False


class SettingsTestRequest(BaseModel):
    """覆盖字段省略或空白时，使用当前有效通道配置。"""

    channel: Literal["llm", "embedding", "rerank"]
    base_url: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None
    # 表单协议仅用于 LLM 通道的保存前探测。
    protocol: str | None = None


class SettingsTestResponse(BaseModel):
    """连通性测试成功响应；失败时返回 ``{code, message}``。"""

    ok: bool
    channel: str
    latency_ms: int


class LibrarySourceResponse(BaseModel):
    """资料库清单中的单条来源，派生自摄取元数据与库域登记。"""

    name: str
    path: str
    source_hash: str
    # 库域来源身份，用于清单删除与移除定位；无法推导时为 null
    source_id: str | None = None
    # 仅无同步登记引用的手动来源为 true；客户端不得从路径推断
    removable: bool = False
    ingest_status: Literal[
        "ingested",
        "stale",
        "pending",
        "ignored",
        "missing",
        "superseded",
        "removing",
    ]
    index_status: Literal["indexed", "stale", "missing"]
    # 来源目录的上游路径；手动导入条目为 null。
    origin_path: str | None = None


class LibraryResponse(BaseModel):
    sources: list[LibrarySourceResponse]


class LibraryJobItemResponse(BaseModel):
    name: str
    path: str
    status: Literal["created", "updated", "skipped", "ignored", "failed", "removed"]
    detail: str | None = None


class LibraryJobResponse(BaseModel):
    """资料库任务的进度快照。"""

    job_id: str
    kind: Literal["ingest", "rebuild", "scan", "purge", "remove"]
    state: Literal["running", "succeeded", "failed", "cancelled"]
    phase: Literal["scanning", "ingesting", "purging", "indexing"]
    total: int
    done: int
    failed: int
    current: str | None
    items: list[LibraryJobItemResponse]
    error: str | None
    # 图谱自动刷新的结果通知；null 表示无附加信息。
    notice: str | None = None


class LibraryRebuildRequest(BaseModel):
    """全量重建请求：必须显式携带确认标记。"""

    confirm: bool = False


class LibrarySourceInfo(BaseModel):
    """来源目录登记（掩码视图）。"""

    id: str
    path: str
    enabled: bool
    created_at: str
    last_scan_at: str | None


class LibrarySourcesResponse(BaseModel):
    """来源目录登记清单。"""

    sources: list[LibrarySourceInfo]


class LibrarySourceCreateRequest(BaseModel):
    path: str
    enabled: bool = True


class LibrarySourceUpdateRequest(BaseModel):
    """启停来源目录；登记保留。"""

    enabled: bool


class LibrarySourceRemovedResponse(BaseModel):
    removed: bool


class LibraryScanRequest(BaseModel):
    """手动扫描请求；``full`` 跳过 stat 快选、强制全量哈希校验。"""

    full: bool = False


class LibraryScanSettingsResponse(BaseModel):
    """自动扫描间隔（秒；0 = 关闭）与图谱自动刷新开关（缺省关闭）。"""

    interval_secs: int
    graph_auto_refresh: bool = False


class LibraryScanSettingsUpdateRequest(BaseModel):
    """未携带的字段保持原值。"""

    interval_secs: int | None = None
    graph_auto_refresh: bool | None = None


class LibraryPurgeRequest(BaseModel):
    """清理请求：必须显式携带确认标记（唯一物理删除路径）。"""

    confirm: bool = False


class LibraryRemoveRequest(BaseModel):
    """按来源 ID 确认移除；不接受文件路径。"""

    source_id: str
    confirmed: bool = False


class NoteSummaryResponse(BaseModel):
    source_id: str
    source_name: str
    note_path: str
    source_hash: str
    extractor: str


class NotesPageResponse(BaseModel):
    """按 note_path 字典序排序的笔记分页。"""

    notes: list[NoteSummaryResponse]
    total: int
    page: int
    page_size: int


class NoteDetailResponse(NoteSummaryResponse):
    """Markdown 全文（不含 frontmatter）与区块锚点。"""

    anchors: list[str]
    content: str


class GraphStatsResponse(BaseModel):
    nodes: int
    edges: int
    communities: int
    types: dict[str, int]


class GraphNodeResponse(BaseModel):
    entity_id: str
    name: str
    type: str
    degree: int
    community_id: int | None


class GraphEdgeResponse(BaseModel):
    source: str
    target: str
    type: str


class GraphSubgraphResponse(BaseModel):
    """有界子图；结果超限时由服务端截断并标记。"""

    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    truncated: bool
    total_nodes: int
    total_edges: int


class GraphSearchResponse(GraphSubgraphResponse):
    """实体搜索响应，附查询词与生效上限。"""

    query: str
    limit: int


class WikiEntrySummaryResponse(BaseModel):
    """条目文件 mtime 即生成时间。"""

    community_id: int
    title: str
    generated_at: str


class WikiEntriesResponse(BaseModel):
    entries: list[WikiEntrySummaryResponse]


class WikiEntryDetailResponse(BaseModel):
    community_id: int
    title: str
    content: str
    generated_at: str
