"""CLI 应用骨架：Typer 实例、缺省目录常量与模型供给选项/枚举。"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="siku",
    help="siku（四库）—— 本地优先的个人知识库：万能摄取、知识图谱、LLM wiki、自然语言问答。",
    no_args_is_help=True,
)

DEFAULT_VAULT = Path("vault")
DEFAULT_DATA_DIR = Path("data")
DEFAULT_UI_DIST = Path("ui") / "dist"
# 基线按通道命名 {channel}.json；旧版 retrieval-baseline-v0.json 仅作历史记录。
BASELINES_DIR = Path("benchmarks") / "baselines"

# ---- 模型供给 CLI 选项；缺省时按环境变量 > config.toml 分层解析 ----
EmbeddingBaseUrlOpt = Annotated[
    str | None,
    typer.Option(
        "--embedding-base-url",
        help="openai 兼容 embedding 端点 base URL（如 Ollama: http://127.0.0.1:11434/v1）。",
    ),
]
EmbeddingModelOpt = Annotated[
    str | None,
    typer.Option("--embedding-model", help="embedding 模型名称（如 bge-m3）。"),
]
EmbeddingApiKeyEnvOpt = Annotated[
    str | None,
    typer.Option("--embedding-api-key-env", help="存放 embedding 端点 API key 的环境变量名。"),
]
EmbeddingDimensionsOpt = Annotated[
    int | None,
    typer.Option(
        "--embedding-dimensions",
        min=1,
        help="显式指定向量维度，跳过首索引时的探针请求（防端点返回维度与声明不符）。",
    ),
]


class RerankerMode(StrEnum):
    """重排模式：api=调用 rerank 端点；none=RRF-only（ADR-0009 一等公民）。"""

    API = "api"
    NONE = "none"


RerankerModeOpt = Annotated[
    RerankerMode | None,
    typer.Option(
        "--reranker",
        help="重排模式：api（调用 rerank 端点）或 none（RRF-only）。缺省自动："
        "配置了 rerank 通道即 api，否则 none。",
    ),
]
RerankBaseUrlOpt = Annotated[
    str | None,
    typer.Option("--rerank-base-url", help="rerank 端点 base URL（/rerank 通用形）。"),
]
RerankModelOpt = Annotated[
    str | None,
    typer.Option("--rerank-model", help="rerank 模型名称（如 BAAI/bge-reranker-v2-m3）。"),
]
RerankApiKeyEnvOpt = Annotated[
    str | None,
    typer.Option("--rerank-api-key-env", help="存放 rerank 端点 API key 的环境变量名。"),
]


class LlmProtocol(StrEnum):
    """`--llm-protocol` 的合法取值：命令行边界的枚举，与内核 `LLM_PROTOCOLS` 保持一致。

    非法值在命令行解析阶段即被拒绝。
    """

    OPENAI_CHAT = "openai-chat"
    ANTHROPIC = "anthropic"
    OPENAI_RESPONSES = "openai-responses"


LlmProtocolOpt = Annotated[
    LlmProtocol | None,
    typer.Option(
        "--llm-protocol",
        help="LLM 线协议：openai-chat（缺省）/ anthropic / openai-responses；"
        "缺省读分层配置，取值不在名单内当场拒绝。",
    ),
]


def protocol_value(protocol: LlmProtocol | None) -> str | None:
    """枚举转回普通字符串：None 表示该层未设置（与空白串等价）。"""
    return protocol.value if protocol is not None else None
