"""HTTP API 的请求和响应模型。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator

from siku.qa.models import MAX_CANDIDATE_K, MAX_QUESTION_CHARS, MAX_TOP_K
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


class AskRequest(BaseModel):
    """单轮问答请求。"""

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    top_k: int = Field(default=6, ge=1, le=MAX_TOP_K)
    candidate_k: int = Field(default=30, ge=1, le=MAX_CANDIDATE_K)

    @model_validator(mode="after")
    def validate_rank_limits(self) -> AskRequest:
        if self.top_k > self.candidate_k:
            raise ValueError("top_k must not exceed candidate_k")
        return self


class AskCitationResponse(BaseModel):
    """问答回答中的来源引用。"""

    citation_id: str
    source_name: str
    note_path: str
    anchor: str
    chunk_id: str
    source_hash: str
    text: str


class AskRetrievalResponse(BaseModel):
    """问答响应中的检索摘要。"""

    top_k: int
    candidate_k: int
    result_count: int


class AskResponse(BaseModel):
    """带来源的单轮问答响应。"""

    request_id: str
    question: str
    answer: str
    insufficient_evidence: bool
    citations: list[AskCitationResponse]
    retrieval: AskRetrievalResponse
    model: str


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


class ChannelSettingsView(BaseModel):
    """单通道配置的掩码视图：key 只以是否已设置的布尔标记表示。

    `protocol` 仅 LLM 通道消费；embedding/rerank 正常配置下为 None，
    手改文件的越界值在解析/提交校验期报错，不在视图层吞掉。
    """

    base_url: str | None
    model: str | None
    api_key_env: str | None
    protocol: str | None = None
    api_key_set: bool
    env_overrides: list[str]


class AskReadinessView(BaseModel):
    """问答就绪状态：missing/invalid 为稳定的 `<channel>.<field>` 机器 token（无凭证明文）。

    `missing` 是缺项；`invalid` 是跨层合并后取值非法（如环境变量层协议越界）。
    判定口径与请求期通道解析同源（rerank 可选不阻塞）；中文话术由 UI 依据
    token 生成，内核不承载展示文案。
    """

    ready: bool
    missing: list[str]
    invalid: list[str] = Field(default_factory=list)


class LlmEnvFallbackView(BaseModel):
    """LLM 通道厂商环境变量回退的端点描述（不含凭证明文）。

    `vendor` 恒为 `dashscope`（当前唯一回退名单）；四元组与请求期解析同源，
    UI 据此说明「回退生效」的落差，避免空表单被误读为完全未配置。
    """

    vendor: str
    base_url: str
    model: str
    api_key_env: str


class SettingsResponse(BaseModel):
    """三通道文件层掩码视图 + 问答就绪状态（GET /api/settings 响应）。"""

    config_path: str
    llm: ChannelSettingsView
    embedding: ChannelSettingsView
    rerank: ChannelSettingsView
    ask_readiness: AskReadinessView
    llm_env_fallback: LlmEnvFallbackView | None = None


class ChannelSettingsUpdate(BaseModel):
    """单通道提交值：省略字段 = 保持现值；null/空白 = 显式清空；非空 = 设置。

    ``api_key`` 以 ``SecretStr`` 承载，repr/日志展开均为掩码，只在非空时落盘。
    """

    base_url: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None
    protocol: str | None = None


class SettingsUpdateRequest(BaseModel):
    """PUT /api/settings 请求：通道对象省略 = 该通道整体保持不变。"""

    llm: ChannelSettingsUpdate | None = None
    embedding: ChannelSettingsUpdate | None = None
    rerank: ChannelSettingsUpdate | None = None


class SettingsWriteResponse(SettingsResponse):
    """PUT /api/settings 响应：写入后掩码视图 + 中文告警（如需重建索引）。

    `invalid_config_file_overwritten=True` 表示本次保存前配置文件不可解析
    （内容损坏），系统以空的文件层为基底合并本次提交并原子替换了该文件——
    这是「坏文件自救」的显式告知，不静默丢内容（原文件既然不可解析，其可读
    配置量本就为零）。正常写入恒为 False。
    """

    warnings: list[str]
    invalid_config_file_overwritten: bool = False


class SettingsTestRequest(BaseModel):
    """POST /api/settings/test 请求：覆盖字段省略/空白 = 用当前有效通道配置。"""

    channel: Literal["llm", "embedding", "rerank"]
    base_url: str | None = None
    model: str | None = None
    api_key: SecretStr | None = None
    api_key_env: str | None = None
    # 表单当前协议（仅 llm 通道消费）：保存前即可按所选协议探测（决议 #5）
    protocol: str | None = None


class SettingsTestResponse(BaseModel):
    """连通性测试成功响应（失败走既有 ``{code, message}`` 错误体）。"""

    ok: bool
    channel: str
    latency_ms: int


class LibrarySourceResponse(BaseModel):
    """资料库清单中的单条来源（全部派生自既有摄取元数据与库域登记，只读）。"""

    name: str
    path: str
    source_hash: str
    # 真实库域来源身份（清单删除/移除入口的定位键）；无法推导时为 null
    source_id: str | None = None
    # 服务端判定：仅无同步登记引用的手动来源为 true；客户端不得从路径推断
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
    # 来源目录登记的上游路径；手动导入条目为 null（决议 #4）
    origin_path: str | None = None


class LibraryResponse(BaseModel):
    """桌面 vault 来源级清单。"""

    sources: list[LibrarySourceResponse]


class LibraryJobItemResponse(BaseModel):
    """任务内单文件结果。"""

    name: str
    path: str
    status: Literal["created", "updated", "skipped", "ignored", "failed", "removed"]
    detail: str | None = None


class LibraryJobResponse(BaseModel):
    """摄取/重建/扫描/清理/移除任务的进度快照（HTTP 轮询读取）。"""

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


class LibraryRebuildRequest(BaseModel):
    """全量重建请求：必须显式携带确认标记。"""

    confirm: bool = False


class LibrarySourceInfo(BaseModel):
    """一条来源目录登记（库域注册表的掩码视图）。"""

    id: str
    path: str
    enabled: bool
    created_at: str
    last_scan_at: str | None


class LibrarySourcesResponse(BaseModel):
    """来源目录登记清单，按路径排序。"""

    sources: list[LibrarySourceInfo]


class LibrarySourceCreateRequest(BaseModel):
    """注册来源目录：绝对路径。"""

    path: str
    enabled: bool = True


class LibrarySourceUpdateRequest(BaseModel):
    """启停来源目录（登记保留，仅扫描是否遍历）。"""

    enabled: bool


class LibrarySourceRemovedResponse(BaseModel):
    """来源目录移除结果。"""

    removed: bool


class LibraryScanRequest(BaseModel):
    """手动扫描请求；``full`` 跳过 stat 快选、强制全量哈希校验。"""

    full: bool = False


class LibraryScanSettingsResponse(BaseModel):
    """自动扫描间隔设置（秒；0 = 关闭自动扫描）。"""

    interval_secs: int


class LibraryScanSettingsUpdateRequest(BaseModel):
    """自动扫描间隔更新；调度线程每轮现读，免重启生效。"""

    interval_secs: int


class LibraryPurgeRequest(BaseModel):
    """清理请求：必须显式携带确认标记（唯一物理删除路径）。"""

    confirm: bool = False


class LibraryRemoveRequest(BaseModel):
    """单来源确认移除请求：真实来源 ID + 显式确认；不接受文件路径。"""

    source_id: str
    confirmed: bool = False


class NoteSummaryResponse(BaseModel):
    """浏览清单中的单条笔记投影元数据（只读派生）。"""

    source_id: str
    source_name: str
    note_path: str
    source_hash: str
    extractor: str


class NotesPageResponse(BaseModel):
    """浏览清单分页响应：note_path 字典序稳定排序。"""

    notes: list[NoteSummaryResponse]
    total: int
    page: int
    page_size: int


class NoteDetailResponse(NoteSummaryResponse):
    """单篇投影读取：Markdown 全文（剥 frontmatter）与区块锚点序列。"""

    anchors: list[str]
    content: str


class GraphStatsResponse(BaseModel):
    """图谱聚合统计。"""

    nodes: int
    edges: int
    communities: int
    types: dict[str, int]


class GraphNodeResponse(BaseModel):
    """画布节点：度数与社区着色依据。"""

    entity_id: str
    name: str
    type: str
    degree: int
    community_id: int | None


class GraphEdgeResponse(BaseModel):
    """画布边：两端实体 id 与关系类型。"""

    source: str
    target: str
    type: str


class GraphSubgraphResponse(BaseModel):
    """有界子图查询响应：截断标记与候选总数由服务端裁决。"""

    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    truncated: bool
    total_nodes: int
    total_edges: int


class GraphSearchResponse(GraphSubgraphResponse):
    """实体搜索响应：附查询词与生效上限。"""

    query: str
    limit: int


class WikiEntrySummaryResponse(BaseModel):
    """wiki 条目清单条目：时效元数据取条目文件 mtime。"""

    community_id: int
    title: str
    generated_at: str


class WikiEntriesResponse(BaseModel):
    """wiki 条目清单响应。"""

    entries: list[WikiEntrySummaryResponse]


class WikiEntryDetailResponse(BaseModel):
    """wiki 单条读取响应：Markdown 全文 + 时效元数据。"""

    community_id: int
    title: str
    content: str
    generated_at: str
