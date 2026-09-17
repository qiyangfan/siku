"""检索用确定性中文预分词器。

方案：零依赖的确定性 unigram+bigram 预分词——中文按连续汉字 run 同时产出
单字与相邻二元 token，英文/数字/型号（含连字符、点、下划线、斜杠）保留为
整体小写 token，标点与多余空白归一化丢弃。查询与索引进 FTS5 前必须经过
同一 tokenizer（ADR-0003 红线：禁止裸 FTS5 上中文）。

选型理由：词典分词（jieba 等）引入额外依赖与词典资产，而 unigram+bigram
在混合召回架构下只承担"关键词精确召回"职责，语义召回由向量通道承担；
若 bigram 方案成为检索瓶颈，按 ROADMAP 触发器重开 FTS5 分词器选型。
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from collections.abc import Sequence

from siku.retrieve.errors import FtsUnavailableError, InvalidQueryError

# 预分词方案版本：进入索引元数据，变更即要求重建索引
TOKENIZER_VERSION = "cjk-uni-bigram-v1"

# CJK 统一表意文字（含扩展 A 与兼容区）；假名/谚文等暂不在 BM25 分词范围
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

# 英文/数字/型号 token：字母数字开头，可含 - . _ / @ 的连续序列
_TOKEN_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._/@-]*")
# token 尾部允许出现的连接符，剥除避免把句尾标点吸进 token
_TOKEN_TRAILING = "._/@-"


def normalize_text(text: str) -> str:
    """归一化文本：全角转半角、空白折叠为单空格。"""
    normalized = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", normalized)


def tokenize(text: str) -> list[str]:
    """把任意文本切分为 FTS5 可检索 token 序列（保留重复以维持词频）。"""
    normalized = normalize_text(text)
    tokens: list[str] = []
    position = 0
    length = len(normalized)
    while position < length:
        char = normalized[position]
        if _CJK_RE.match(char):
            run_end = position + 1
            while run_end < length and _CJK_RE.match(normalized[run_end]):
                run_end += 1
            run = normalized[position:run_end]
            tokens.extend(run)
            tokens.extend(run[start : start + 2] for start in range(len(run) - 1))
            position = run_end
            continue
        matched = _TOKEN_RE.match(normalized, position)
        if matched:
            token = matched.group().rstrip(_TOKEN_TRAILING).lower()
            if token:
                tokens.append(token)
            position = matched.end()
            continue
        position += 1
    return tokens


def tokenize_query(query: str) -> list[str]:
    """切分用户查询；无有效 token 属于用户输入错误而非空结果。"""
    tokens = tokenize(query)
    if not tokens:
        raise InvalidQueryError(f"Query contains no searchable tokens: {query!r}")
    return tokens


def build_fts_match(tokens: Sequence[str]) -> str:
    """把 token 序列转为 FTS5 MATCH 表达式（OR 召回，引号防语法注入）。"""
    seen: dict[str, None] = dict.fromkeys(tokens)
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in seen)


def ensure_fts5_available() -> None:
    """探测当前 SQLite 构建是否带 FTS5；缺失时给出用户可读错误。"""
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE fts5_probe USING fts5(content)")
    except sqlite3.OperationalError as exc:
        raise FtsUnavailableError(
            "The SQLite build in use lacks FTS5 support; "
            "full-text retrieval is unavailable. "
            "Install a Python build compiled with SQLITE_ENABLE_FTS5."
        ) from exc
    finally:
        if connection is not None:
            connection.close()
