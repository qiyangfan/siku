"""检索链路的错误体系。

约定：异常 message 面向开发者用英文（根 AGENTS.md 铁律），
CLI 层按错误类映射为简体中文的用户可读文案。
错误分类必须稳定，供 CLI 与未来 HTTP 层做归一化映射。
"""

from __future__ import annotations


class RetrievalError(RuntimeError):
    """检索链路失败的领域错误基类。"""


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
    """模型端点未配置、凭证被拒或端点不可用（BYOK，ADR-0009）。"""


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
