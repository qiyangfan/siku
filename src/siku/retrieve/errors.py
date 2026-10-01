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
    """模型端点未配置、凭证被拒或端点不可用（BYOK，ADR-0009）。

    三种语义由子类分型（change `fix-model-supply-error-surfacing` 决议 #1）：
    文案层按子类出不同指引，而所有既有 `except ModelNotAvailableError` 处理器
    （reranker=none 判定、settings 读写、serve 启动）行为零回退。
    """


class ModelCredentialError(ModelNotAvailableError):
    """端点拒绝了当前凭证（HTTP 401/403），与「未配置」不是一回事。

    `channel` 是结构化通道标识（`llm`/`embedding`/`rerank`），供文案层据此指
    引「核对这一通道的 key 与端点是否成套」，而不是让用户去补全 base_url/model。
    走 args 位置参（照 `ProtocolConfigError.kind` 先例）以保住基类 `__reduce__`
    的 copy/deepcopy/pickle 圆厂。凭证值绝不进 message。
    """

    def __init__(self, message: str, channel: str) -> None:
        super().__init__(message, channel)
        self.channel = channel


class ModelConfigFileError(ModelNotAvailableError):
    """配置文件对模型供给无效：内容不可解析，或某字段取值不在允许范围。

    与「文件读不到」（OSError，内容未知）刻意分型：前者用户可以「重新保存」覆盖
    自救，后者覆盖即丢配置，必须继续报错。change
    `fix-model-supply-error-surfacing` 决议 #3。

    非法取值归入本类而不是另造一种运行期状态：文件层是唯一的外部输入源，坏值在
    载入点（`model_supply.load_config`）就该拒——否则「无效配置」会以合法对象的形态
    流到解析、就绪判定与前端，逼每一层都加一条善后分支。

    `detail` 是服务端自撰的**字段级**补充说明（例如「[llm] protocol 仅支持 …」），
    供文案指明到底哪一处要改；它 MUST NOT 回显用户原值（同 `ModelCredentialError`
    不回显凭证的纪律），走 args 位置参以保住基类 `__reduce__` 的 copy/pickle 圆厂。
    """

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message, detail)
        self.detail = detail


class ModelConfigFileUnreadableError(ModelNotAvailableError):
    """配置文件读不到（权限/IO 故障）——内容未知，与「不可解析」不同类。

    不可解析=知道文件是坏的，可以覆盖自救；读不到=不知道文件里有什么，覆盖即
    毁掉可能完好的配置，因此本类不得进入覆盖路径，文案也不得说「通道未配置」
    （通道可能配得好好的，只是文件读不出来）。change 的 model-supply 决议 #3
    要求两型分家，此前共用基类等式于把「读不到」顶替成「未配置」。
    """


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
