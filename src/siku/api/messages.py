"""CLI 与 HTTP API 共用的领域错误文案和归一化映射。

只读读取面（浏览/图谱/wiki 清单与单条）的错误无 CLI 对应路径，但同样集中在
本模块（map_read_error）成文：全部错误码与文案保持单一映射来源，端点禁止
内联字面量。错误语义边界见 api/reading.py 模块 docstring。
"""

from __future__ import annotations

from dataclasses import dataclass

from siku.api.reading import (
    GraphEntityNotFoundError,
    NoteNotFoundError,
    WikiEntryNotFoundError,
    WikiEntryReadError,
    WikiMissingError,
)
from siku.graph.errors import (
    GraphArtifactsMissingError,
    GraphArtifactsStaleError,
    GraphError,
    GraphExtractionError,
    GraphStoreCorruptError,
    LlmConnectionError,
    LlmEmptyResponseError,
    LlmInputTooLongError,
    LlmNotConfiguredError,
    LlmProviderError,
    LlmRateLimitError,
)
from siku.ingest import IngestError
from siku.model_supply import config_file_path
from siku.retrieve.errors import (
    BaselineExistsError,
    EvaluationError,
    FixtureMismatchError,
    FtsUnavailableError,
    GoldenSetError,
    IndexBusyError,
    IndexCorruptError,
    IndexUnavailableError,
    InvalidQueryError,
    ModelConfigMismatchError,
    ModelNotAvailableError,
    NoteParseError,
    NotesDirMissingError,
    ProviderError,
    RetrievalError,
)


@dataclass(frozen=True)
class ErrorMapping:
    """领域错误在用户面上的稳定 HTTP 表达。"""

    status_code: int
    code: str
    message: str


def map_ask_error(exc: Exception, *, api_key_env: str) -> ErrorMapping:
    """映射问答错误；不复用图谱的缓存/续传文案。"""
    if isinstance(exc, LlmNotConfiguredError):
        return ErrorMapping(
            503,
            "llm_not_configured",
            f"未配置 LLM API key：请先设置环境变量 {api_key_env}，再重试问答。",
        )
    if isinstance(exc, LlmInputTooLongError):
        return ErrorMapping(
            503,
            "llm_input_too_long",
            "问答上下文或模型输入过长：请减少检索范围或更换上下文窗口更大的模型。",
        )
    if isinstance(exc, LlmRateLimitError):
        return ErrorMapping(503, "llm_rate_limited", "LLM 服务限流：请稍后重试。")
    if isinstance(exc, LlmConnectionError):
        return ErrorMapping(503, "llm_connection_error", "无法连接 LLM 服务：请检查端点后重试。")
    if isinstance(exc, LlmEmptyResponseError):
        return ErrorMapping(503, "llm_empty_response", "LLM 返回了空内容：请重试或更换模型。")
    if isinstance(exc, LlmProviderError):
        return ErrorMapping(
            503,
            "llm_provider_error",
            "LLM 未返回可验证的问答结果：请检查配置后重试。",
        )
    return map_domain_error(exc, api_key_env=api_key_env)


def map_domain_error(exc: Exception, *, api_key_env: str) -> ErrorMapping:
    """将领域错误映射为稳定状态码、错误码和中文文案。"""
    if isinstance(exc, IngestError):
        return ErrorMapping(
            422, "ingest_error", "摄取失败：请检查源路径与文档格式；技术详情见日志。"
        )
    if isinstance(exc, LlmNotConfiguredError):
        return ErrorMapping(
            503,
            "llm_not_configured",
            f"未配置 LLM API key：请先设置环境变量 {api_key_env} 为你的 openai 兼容服务 "
            "API key（如 DeepSeek），再重新执行本命令。",
        )
    if isinstance(exc, LlmInputTooLongError):
        return ErrorMapping(
            503,
            "llm_input_too_long",
            "LLM 输入超出模型上下文窗口：请更换长上下文模型后重试；已完成部分已入缓存。",
        )
    if isinstance(exc, LlmRateLimitError):
        return ErrorMapping(
            503,
            "llm_rate_limited",
            "LLM 服务限流：请稍后重试；已完成部分已入缓存，重跑自动续传。",
        )
    if isinstance(exc, LlmConnectionError):
        return ErrorMapping(
            503, "llm_connection_error", "无法连接 LLM 服务：请检查网络与端点可达性后重试。"
        )
    if isinstance(exc, LlmEmptyResponseError):
        return ErrorMapping(
            503, "llm_empty_response", "LLM 返回了空内容：请重试；若反复出现请更换模型。"
        )
    if isinstance(exc, LlmProviderError):
        return ErrorMapping(
            503,
            "llm_provider_error",
            "LLM 服务调用失败：请检查 API key、端点与模型名称；技术详情见日志。",
        )
    if isinstance(exc, GraphExtractionError):
        return ErrorMapping(
            422,
            "graph_extraction_error",
            "抽取输出解析失败：LLM 输出不符合约定的 JSON 结构；技术详情见日志。",
        )
    if isinstance(exc, GraphArtifactsMissingError):
        return ErrorMapping(
            409,
            "graph_artifacts_missing",
            "图谱产物缺失：请先执行 siku graph 构建图谱，再生成 wiki。",
        )
    if isinstance(exc, GraphStoreCorruptError):
        # 整库级派生产物损坏 → 409 状态前置（单条目级损坏走 422，边界见 reading.py）
        return ErrorMapping(
            409,
            "graph_store_corrupt",
            "图谱派生产物已损坏：请删除 data/graph 目录后重新执行本命令，"
            "缓存与图谱会自动全量重建。",
        )
    if isinstance(exc, GraphArtifactsStaleError):
        return ErrorMapping(
            409, "graph_artifacts_stale", "图谱产物与当前摘要配置不一致：请重新执行 siku graph。"
        )
    if isinstance(exc, ModelNotAvailableError):
        return ErrorMapping(
            503,
            "model_not_available",
            "模型端点未配置或不可用：siku 不内置模型（BYOK），请在 "
            f"{config_file_path()} 对应通道段补全 base_url 与 model，"
            "或用 CLI 参数指定端点（embedding 通道示例：--embedding-base-url "
            "http://127.0.0.1:11434/v1 --embedding-model bge-m3；rerank 通道示例："
            "--rerank-base-url / --rerank-model）后重试。",
        )
    if isinstance(exc, FtsUnavailableError):
        return ErrorMapping(
            503,
            "fts_unavailable",
            "当前 SQLite 缺少 FTS5 全文检索能力："
            "请更换为启用 SQLITE_ENABLE_FTS5 的 Python 构建后重试。",
        )
    if isinstance(exc, ProviderError):
        return ErrorMapping(
            503,
            "provider_error",
            "模型端点调用失败：请检查端点可达性、API 凭证与模型名称后重试；技术详情见日志。",
        )
    if isinstance(exc, IndexBusyError):
        return ErrorMapping(409, "index_busy", "检索索引暂不可用：可能正在重建索引，请稍后重试。")
    if isinstance(exc, ModelConfigMismatchError):
        return ErrorMapping(
            409,
            "model_config_mismatch",
            "已建索引的模型配置与当前不一致：请执行 siku index --rebuild 显式重建索引。",
        )
    if isinstance(exc, IndexCorruptError):
        return ErrorMapping(
            409, "index_corrupt", "检索索引已损坏，请执行 siku index --rebuild 重建索引。"
        )
    if isinstance(exc, IndexUnavailableError):
        return ErrorMapping(
            409, "index_unavailable", "检索索引不可用，请先执行 siku index 建立索引。"
        )
    if isinstance(exc, InvalidQueryError):
        return ErrorMapping(422, "invalid_query", "查询无效：请输入包含有效检索词的非空查询。")
    if isinstance(exc, NotesDirMissingError):
        return ErrorMapping(
            422,
            "notes_dir_missing",
            "未找到 vault/notes 目录：请先执行 siku ingest 摄取文档，再执行 siku index。",
        )
    if isinstance(exc, NoteParseError):
        return ErrorMapping(
            422,
            "note_parse_error",
            "投影解析失败：vault/notes 下的 Markdown 投影缺失必需 frontmatter 字段或格式不符；"
            "技术详情见日志。",
        )
    if isinstance(exc, GoldenSetError):
        return ErrorMapping(
            422,
            "golden_set_error",
            "golden set 文件格式不合法：请检查 JSONL 每行的 id、query、expected 字段；"
            "技术详情见日志。",
        )
    if isinstance(exc, FixtureMismatchError):
        return ErrorMapping(
            422,
            "fixture_mismatch",
            "基线快照与当前 golden set 内容指纹不一致：请改用与该基线配套的 fixture，"
            "或显式生成新版本基线；技术详情见日志。",
        )
    if isinstance(exc, BaselineExistsError):
        return ErrorMapping(
            409,
            "baseline_exists",
            "已存在同名基线文件：为保留历史证据，旧基线不可覆盖；"
            "请改用新的版本号路径（如 retrieval-baseline-v1.json）。",
        )
    if isinstance(exc, EvaluationError):
        return ErrorMapping(
            500,
            "evaluation_error",
            "评测执行失败：基线快照缺失或损坏。"
            "首次运行请加 --save-baseline 生成基线；已有基线请用 --baseline 指定文件；"
            "技术详情见日志。",
        )
    if isinstance(exc, GraphError):
        return ErrorMapping(500, "graph_error", "图谱操作失败，请重试；技术详情见日志。")
    if isinstance(exc, RetrievalError):
        return ErrorMapping(
            500,
            "retrieval_error",
            "检索操作失败：请重试；若反复出现请执行 siku index --rebuild 重建索引；"
            "技术详情见日志。",
        )
    return ErrorMapping(500, "internal_error", "服务内部错误，请重试；技术详情见日志。")


def map_read_error(exc: Exception, *, api_key_env: str) -> ErrorMapping:
    """只读读取面（浏览/图谱/wiki 清单与单条）的错误归一化映射。

    读取面错误无 CLI 对应路径，「与 CLI 共享同一映射来源」在此落为：全部读
    错误码与文案只在本函数成文，端点禁止内联字面量。读上下文对同一领域错误
    的语义可与写路径不同并在此显式成文——GraphArtifactsMissingError 对读请求
    是 404 资源未生成，对写请求才是 409 状态前置；其余领域错误回落
    map_domain_error（含 409 graph_store_corrupt / 422 note_parse_error）。
    """
    if isinstance(exc, NoteNotFoundError):
        return ErrorMapping(404, "note_not_found", "请求的笔记不存在：可能已被移除或重新摄取。")
    if isinstance(exc, GraphEntityNotFoundError):
        return ErrorMapping(
            404,
            "graph_entity_not_found",
            "图谱中不存在该实体：图谱可能已重建合并，请刷新后重试。",
        )
    if isinstance(exc, WikiEntryNotFoundError):
        return ErrorMapping(
            404,
            "wiki_entry_not_found",
            "请求的 wiki 条目不存在：条目可能已随图谱重建更新。",
        )
    if isinstance(exc, WikiEntryReadError):
        return ErrorMapping(
            422,
            "wiki_entry_parse_error",
            "wiki 条目读取失败：data/wiki/entries 下的条目文件可能已损坏；"
            "请重新执行 siku wiki 重新生成；技术详情见日志。",
        )
    if isinstance(exc, WikiMissingError):
        return ErrorMapping(404, "wiki_missing", "wiki 尚未生成：请先构建图谱并执行 siku wiki。")
    if isinstance(exc, GraphArtifactsMissingError):
        return ErrorMapping(404, "graph_missing", "图谱尚未构建：请先执行 siku graph 构建图谱。")
    return map_domain_error(exc, api_key_env=api_key_env)


def retrieval_error_message(exc: RetrievalError) -> str:
    """返回 CLI 使用的检索错误文案。"""
    return map_domain_error(exc, api_key_env="SIKU_LLM_API_KEY").message


def graph_error_message(exc: GraphError, api_key_env: str) -> str:
    """返回 CLI 使用的图谱错误文案。"""
    return map_domain_error(exc, api_key_env=api_key_env).message


def ingest_error_message(exc: IngestError) -> str:
    """返回 CLI 使用的摄取错误文案。"""
    return map_domain_error(exc, api_key_env="SIKU_LLM_API_KEY").message
