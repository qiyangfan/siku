"""CLI 与 HTTP API 共用的领域错误文案和归一化映射。

读取面错误也集中在此成文，端点不得内联错误字面量；边界见 api/reading.py。
HTTP 指引面向设置页，CLI 指引面向终端，两者共用状态码与错误码。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
    LlmAuthError,
    LlmConnectionError,
    LlmEmptyResponseError,
    LlmInputTooLongError,
    LlmNotConfiguredError,
    LlmProviderError,
    LlmRateLimitError,
)
from siku.ingest import (
    ConverterUnavailableIngestError,
    CorruptDocumentIngestError,
    EncryptedDocumentIngestError,
    IngestError,
    LegacyOfficeFormatError,
    ScannedPdfIngestError,
)
from siku.model_supply import ProtocolConfigError, config_file_path
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
    ModelConfigFileError,
    ModelConfigFileUnreadableError,
    ModelConfigMismatchError,
    ModelCredentialError,
    ModelNotAvailableError,
    NoteParseError,
    NotesDirMissingError,
    ProviderError,
    RetrievalError,
)

# 文案面：命令行（有文件与参数语境）/ HTTP（只有「设置」页语境）
ErrorSurface = Literal["cli", "http"]

# 通道 token → 中文面标签（结构化字段驱动文案，不解析英文 message）
_CHANNEL_LABELS: dict[str, str] = {"llm": "LLM", "embedding": "embedding", "rerank": "rerank"}


def _channel_label(channel: str) -> str:
    return _CHANNEL_LABELS.get(channel, channel or "模型")


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
            f"未配置 LLM API key：请在「设置」页为 LLM 通道填写 base_url、model 与"
            f" api_key，保存后立即生效；也可设置环境变量 {api_key_env}。完成后重试问答。",
        )
    if isinstance(exc, LlmAuthError):
        return ErrorMapping(
            503,
            "llm_provider_error",
            "LLM 端点拒绝了当前凭证：请到「设置」页核对 LLM 通道的 api_key 与 base_url "
            "是否成套（同一厂商同一账号；不同厂商的 key 不能跨端点使用），"
            "保存后免重启生效，再回到问答重试。",
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
    if isinstance(exc, ModelNotAvailableError):
        # 统一交给通用映射：端点错误的各种语义已在那里分型。
        return map_domain_error(exc, api_key_env=api_key_env, surface="http")
    return map_domain_error(exc, api_key_env=api_key_env, surface="http")


def protocol_error_mapping(exc: ProtocolConfigError, *, surface: ErrorSurface) -> ErrorMapping:
    """映射 HTTP、探测和 CLI 的协议错误，并按配置来源生成指引。

    文件值在载入时校验，命令行枚举由参数解析拒绝；此处处理环境变量或程序传入的非法值。
    """
    if exc.kind == "channel_unsupported":
        if surface == "http":
            return ErrorMapping(
                503,
                "invalid_settings",
                "embedding/rerank 通道不支持 protocol 字段（仅 LLM 通道可用）：该字段由启动服务时"
                "传入的通道配置携带，优先级高于本机配置文件，在「设置」页保存覆盖不了它——"
                "请修正启动服务的那个来源后重启服务。",
            )
        return ErrorMapping(
            503,
            "invalid_settings",
            "embedding/rerank 通道不支持 protocol 字段（仅 LLM 通道可用）：该字段由程序传入的"
            f"通道配置携带，请从调用处删除它；{config_file_path()} 的同名字段在读取时即被拒绝，"
            "不是本条错误的原因。",
        )
    if surface == "http":
        return ErrorMapping(
            503,
            "invalid_settings",
            "LLM 通道的接口协议（protocol）取值非法：仅支持 openai-chat / anthropic / "
            "openai-responses。该值来自环境变量 SIKU_LLM_PROTOCOL，优先级高于本机配置文件，"
            "在「设置」页保存覆盖不了它——请在启动服务的那个环境里取消或修正该变量后重启服务。",
        )
    return ErrorMapping(
        503,
        "invalid_settings",
        "LLM 通道的接口协议（protocol）取值非法：仅支持 openai-chat / anthropic / "
        "openai-responses。该值来自环境变量 SIKU_LLM_PROTOCOL，优先级高于 "
        f"{config_file_path()} 的 [llm] protocol——请取消或修正该变量后重新执行本命令。",
    )


def map_domain_error(
    exc: Exception, *, api_key_env: str, surface: ErrorSurface = "cli"
) -> ErrorMapping:
    """将领域错误映射为稳定状态码、错误码和中文文案。

    `surface="http"` 的指引指向设置页，`surface="cli"` 的指引面向终端。
    凭证与配置文件错误是通用错误的子类，必须先于基类匹配。
    """
    if isinstance(exc, ScannedPdfIngestError):
        return ErrorMapping(
            422,
            "scanned_pdf_no_text",
            "该 PDF 没有可提取的文字（很可能是扫描件或纯图片 PDF）：请先用 OCR 工具"
            "（或系统自带的识别功能）把它转换为含文字层的 PDF，再重新导入。",
        )
    if isinstance(exc, LegacyOfficeFormatError):
        return ErrorMapping(
            422,
            "legacy_office_format",
            "旧版二进制 Office 格式（.doc/.ppt/.xls）不受支持：请在 Office 或 WPS 中"
            "把文档另存为对应的现代格式（.docx/.pptx/.xlsx）后再导入。",
        )
    if isinstance(exc, EncryptedDocumentIngestError):
        return ErrorMapping(
            422,
            "encrypted_document",
            "该文档已加密，无法读取：请先解除密码保护后重新导入。",
        )
    if isinstance(exc, CorruptDocumentIngestError):
        return ErrorMapping(
            422,
            "corrupt_document",
            "该文件不是可解析的文档（可能已损坏，或扩展名与实际内容不符）："
            "请确认能正常打开后重试，或更换导出的源文件。",
        )
    if isinstance(exc, ConverterUnavailableIngestError):
        return ErrorMapping(
            503,
            "converter_unavailable",
            "文档转换工具不可用：桌面安装包应随包携带该工具，请重新安装应用；"
            "开发/命令行环境请安装 pandoc（https://pandoc.org/installing.html）后重试。",
        )
    if isinstance(exc, IngestError):
        return ErrorMapping(
            422, "ingest_error", "摄取失败：请检查源路径与文档格式；技术详情见日志。"
        )
    if isinstance(exc, LlmNotConfiguredError):
        if surface == "http":
            return ErrorMapping(
                503,
                "llm_not_configured",
                "未配置 LLM API key：请到「设置」页为 LLM 通道填写 api_key"
                "（或 api_key_env），保存后免重启生效，再重试。",
            )
        return ErrorMapping(
            503,
            "llm_not_configured",
            f"未配置 LLM API key：请先设置环境变量 {api_key_env} 为你的 openai 兼容服务 "
            "API key（如 DeepSeek），再重新执行本命令。",
        )
    if isinstance(exc, LlmAuthError):
        # 凭证被拒的出路与响应不可解析不同，先单独返回。
        if surface == "http":
            return ErrorMapping(
                503,
                "llm_provider_error",
                "LLM 端点拒绝了当前凭证：请到「设置」页核对 LLM 通道的 api_key 与 base_url 是否成套"
                "（同一厂商同一账号；不同厂商的 key 不能跨端点使用），保存后免重启生效，再重试。",
            )
        return ErrorMapping(
            503,
            "llm_provider_error",
            "LLM 端点拒绝了当前凭证：请核对 api_key / api_key_env 与 base_url 是否成套"
            f"（同一厂商同一账号；不同厂商的 key 不能跨端点使用）；配置见 {config_file_path()} 的 "
            "[llm] 段，或用 --llm-base-url / --api-key-env 指定后重试。",
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
        if surface == "http":
            return ErrorMapping(
                503,
                "llm_provider_error",
                "LLM 服务调用失败：请到「设置」页检查 LLM 通道的 base_url、model 与"
                "接口协议是否匹配该端点，保存后免重启生效再重试；技术详情见日志。",
            )
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
        # 整库损坏返回 409；单条目损坏走 422。
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
    if isinstance(exc, ModelCredentialError):
        # 先于 ProviderError 匹配，避免落入通用文案。
        label = _channel_label(exc.channel)
        if surface == "http":
            return ErrorMapping(
                503,
                "model_not_available",
                f"{label} 端点拒绝了当前凭证：请到「设置」页核对该通道的 api_key 与 base_url "
                "是否成套（同一厂商同一账号；不同厂商的 key 不能跨端点使用），"
                "保存后免重启生效，再重试。",
            )
        return ErrorMapping(
            503,
            "model_not_available",
            f"{label} 端点拒绝了当前凭证：请核对该通道的 api_key / api_key_env 与 base_url 是否成套"
            "（同一厂商同一账号；不同厂商的 key 不能跨端点使用）；配置见 "
            f"{config_file_path()} 的 [{exc.channel}] 段，"
            f"或用 --{exc.channel}-api-key-env 指定后重试。",
        )
    if isinstance(exc, ModelConfigFileUnreadableError):
        # 文件内容未知，覆盖会毁掉可能完好的配置，也不能按「未配置」指引。
        if surface == "http":
            return ErrorMapping(
                503,
                "config_file_unreadable",
                "模型配置文件当前无法读取（权限或磁盘故障，不是内容损坏）：请修复该文件"
                "的可读性后重试。为避免毁掉可能完好的配置，本次不会由保存覆盖它；"
                "若确认不再保留其中的配置，可删除该文件后重新配置——删除只影响模型配置，"
                "不影响已导入的资料与索引。",
            )
        return ErrorMapping(
            503,
            "config_file_unreadable",
            f"模型配置文件当前无法读取：{config_file_path()} 因权限或 IO 故障打不开"
            "（内容未知，不是格式问题）。请修复该文件的可读性后重试；"
            "确认不再需要其中的配置时可删除该文件——删除只影响模型配置，"
            "不影响已摄取语料与索引。",
        )
    if isinstance(exc, ModelConfigFileError):
        # 本类覆盖不可解析与取值非法两种形态，出路相同；detail 是字段级补充。
        hint = f"{exc.detail}。" if exc.detail else ""
        if surface == "http":
            return ErrorMapping(
                503,
                "invalid_config_file",
                "模型配置文件对模型供给无效（内容不可解析，或字段取值非法）："
                + hint
                + "可在「设置」页重新填写并保存，本次保存会覆盖该文件并免重启生效；"
                "也可删除本机配置文件后重新配置——删除只影响模型配置，"
                "不影响已导入的资料与索引。",
            )
        return ErrorMapping(
            503,
            "invalid_config_file",
            f"模型配置文件对模型供给无效：{config_file_path()} 无法作为配置读取"
            "（内容不是合法 TOML、段类型不符，或字段取值不在允许范围）。"
            + hint
            + "请修正或删除该文件后重试——删除只影响模型配置，"
            "不影响已摄取语料与索引；修复前任何通道配置都无法生效。",
        )
    if isinstance(exc, ProtocolConfigError):
        return protocol_error_mapping(exc, surface=surface)
    if isinstance(exc, ModelNotAvailableError):
        if surface == "http":
            return ErrorMapping(
                503,
                "model_not_available",
                "模型端点未配置或不可用：请到「设置」页补全对应通道的 base_url 与 model"
                "（LLM 通道另需 API key），保存后免重启生效，再重试。",
            )
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
        if surface == "http":
            return ErrorMapping(
                503,
                "provider_error",
                "模型端点调用失败：请到「设置」页核对该通道的端点可达性、凭证与模型名称，"
                "或先用「测试连接」验证后再重试；技术详情见日志。",
            )
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
    """读取面错误归一化；图谱产物缺失返回 404，其余复用 HTTP 面通用映射。"""
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
    return map_domain_error(exc, api_key_env=api_key_env, surface="http")


def retrieval_error_message(exc: RetrievalError) -> str:
    return map_domain_error(exc, api_key_env="SIKU_LLM_API_KEY").message


def graph_error_message(exc: GraphError, api_key_env: str) -> str:
    return map_domain_error(exc, api_key_env=api_key_env).message


def ingest_error_message(exc: IngestError) -> str:
    return map_domain_error(exc, api_key_env="SIKU_LLM_API_KEY").message
