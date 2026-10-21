"""检索领域错误；上层将其映射为中文指引。"""

from __future__ import annotations


class RetrievalError(RuntimeError):
    """检索处理失败的领域错误基类。"""


class NoteParseError(RetrievalError):
    """Markdown 投影缺失必需 frontmatter 字段或格式不符合约定。"""


class NotesDirMissingError(NoteParseError):
    """`vault/notes/` 目录不存在，需要先执行摄取而非索引。"""


class InvalidQueryError(RetrievalError):
    """查询输入非法（空 query、仅标点等），属于用户输入错误而非系统故障。"""


class IndexUnavailableError(RetrievalError):
    """索引不存在或损坏，无法执行查询，需要先执行 `siku index` 或 `--rebuild`。"""


class IndexBusyError(IndexUnavailableError):
    """查询撞上索引版本切换窗口或并发写入的瞬态不可用，重试即可恢复。"""


class ModelConfigMismatchError(IndexUnavailableError):
    """已建索引的模型标识/向量维度与当前配置不一致，拒绝混用，要求显式重建。"""


class IndexCorruptError(IndexUnavailableError):
    """SQLite 元数据与向量库提交标记不一致，索引处于损坏状态。"""


class FtsUnavailableError(RetrievalError):
    """当前 SQLite 构建缺少 FTS5 全文检索能力。"""


class ModelNotAvailableError(RetrievalError):
    """模型端点未配置或不可用；具体原因由子类区分。"""


class ModelCredentialError(ModelNotAvailableError):
    """端点以 HTTP 401/403 拒绝凭证；``channel`` 标识端点通道，错误消息不含凭证。"""

    def __init__(self, message: str, channel: str) -> None:
        super().__init__(message, channel)
        self.channel = channel


class ModelConfigFileError(ModelNotAvailableError):
    """配置文件内容不可解析或字段值越界；与内容未知、不可覆盖的读错误区分。

    ``detail`` 提供字段级提示，不回显用户原值。
    """

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message, detail)
        self.detail = detail


class ModelConfigFileUnreadableError(ModelNotAvailableError):
    """配置文件因权限或 IO 错误无法读取，内容未知且不可覆盖。"""


class ProviderError(RetrievalError):
    """模型推理失败（模型异常、空返回、限流、断连等）。"""


class GoldenSetError(RetrievalError):
    """golden set fixture 格式不合法或覆盖场景不足。"""


class EvaluationError(RetrievalError):
    """评测流程失败（基线缺失、基线格式损坏等）。"""


class BaselineExistsError(EvaluationError):
    """目标基线文件已存在；旧基线不可覆盖，必须生成新版本文件。"""


class FixtureMismatchError(EvaluationError):
    """基线快照与当前 golden set 指纹不一致，拒绝以此基线作门禁比较。"""
